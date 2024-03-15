import asyncio
import re
import string
import time
from random import choices, randrange
from urllib.parse import unquote
from _config import Config
from shared import Shared
from camera import Camera
from log import Log


class Client:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        peername = writer.get_extra_info('peername')
        self.host = peername[0]
        self.tcp_port = peername[1]
        self.camera_hash, self.session_id = None, None
        self.udp_ports = {}

    @staticmethod
    async def listen():
        """ One listener for all clients
        """
        host = Config.rtsp_host if hasattr(Config, 'rtsp_host') else '0.0.0.0'
        Log.write(f'Client: start listening {host}:{Config.rtsp_port}')

        server = await asyncio.start_server(_handle, host, Config.rtsp_port)
        async with server:
            await server.serve_forever()

    async def handle(self, data):
        """ Communicate with clients
        """
        try:
            ask = data.decode()
        except (Exception,):
            Log.print(f"Client: warning: can't decode this ask, skipped:\n{data}")
            return

        option = await self._request(ask)
        self.session_id = _get_session_id(ask)

        if option == 'OPTIONS':
            await self._response('Public: OPTIONS, DESCRIBE, SETUP, TEARDOWN, PLAY')

        if option == 'DESCRIBE':
            sdp = self._get_description()
            await self._response(
                'Content-Type: application/sdp',
                f'Content-Length: {len(sdp) + 4}',
                '',
                sdp)

        elif option == 'SETUP':
            await self._response(
                self._get_transport_line(ask),
                f'Session: {self.session_id};timeout=60')

        elif option == 'PLAY':
            # Now we are ready to share this instance
            Shared.data[self.camera_hash]['clients'][self.session_id] = self

            camera = Shared.data[self.camera_hash]['camera']

            # Start camera's playing before client's playing because we need to get RTP info first
            await camera.play()

            res = [f'Session: {self.session_id}']
            rtp_info = self._get_rtp_info()
            if rtp_info:
                res.append(rtp_info)

            await self._response(*res)

            await self._check_web_limit()

            info = f'Client: play [{self.camera_hash}] [{self.session_id}] [{self.host}] {self.user_agent}'
            Log.write(info, self.host)

            # In TCP mode we'll stop listening rtsp
            if Config.tcp_mode:
                return True  # Handling is over, stop self._handle loop

        elif option == 'TEARDOWN':
            await self._response(f'Session: {self.session_id}')

    async def write(self, frame):
        if self.writer.transport.is_closing():
            await self.close()
            return
        self.writer.write(frame)

    async def close(self):
        if not self.camera_hash:
            return
        clients = Shared.data[self.camera_hash]['clients']
        if not self.session_id or self.session_id not in clients:
            return
        try:
            if not self.writer.transport.is_closing():
                self.writer.close()
                await self.writer.wait_closed()
        except (Exception,):
            pass

        del clients[self.session_id]

        Log.write(f'Client closed [{self.camera_hash}] [{self.session_id}] [{self.host}]', self.host)

        # If last client is closed, close the camera connection too
        if not clients:
            try:
                await Shared.data[self.camera_hash]['camera'].close()
            except Exception as e:
                Log.print(f"Client: error: can't close the camera {self.camera_hash}: {e}")
            Shared.data[self.camera_hash]['camera'] = None

    def _get_rtp_info(self):
        """ Build new "RTP-Info" line (for UDP mode only)
        """
        camera = Shared.data[self.camera_hash]['camera']
        rtp_info = camera.rtp_info
        if not rtp_info:
            return

        sdp = camera.description

        delta = time.time() - rtp_info['starttime']
        clock_frequency = sdp['video']['clk_freq']  # i.e. 90000 in SDP a=rtpmap:96 H26*/90000
        rtptime = int(rtp_info["rtptime"][0]) + int(delta * clock_frequency)

        res = f'RTP-Info: url=rtsp://{Config.local_ip}:{Config.rtsp_port}/track1;' \
            f'seq={rtp_info["seq"][0]};rtptime={rtptime}'

        if len(rtp_info['seq']) < 2:
            return res

        clock_frequency = sdp['audio']['clk_freq']  # i.e. 8000 in SDP a=rtpmap:8 PCMA/8000
        rtptime = int(rtp_info["rtptime"][1]) + int(delta * clock_frequency)

        res += f',url=rtsp://{Config.local_ip}:{Config.rtsp_port}/track2;' \
            f'seq={rtp_info["seq"][1]};rtptime={rtptime}'

        return res

    async def _request(self, ask):
        """ Parse client's ask
        """
        Log.print(f'~~~ Client: read\n{ask}')
        res = re.match(r'(.+?) rtsps?://.+?:\d+/?(.*?) .+?\r\n', ask)
        if not res:
            raise RuntimeError('invalid ask')

        self.cseq = _get_cseq(ask)
        self.user_agent = _get_user_agent(ask)

        option = res.group(1)

        if not self.camera_hash:
            camera_hash = unquote(res.group(2))
            if camera_hash not in Config.cameras:
                raise RuntimeError('invalid camera hash')

            self.camera_hash = camera_hash

            # Create the camera connection if not exists
            if not Shared.data[camera_hash]['camera']:
                camera = Camera(camera_hash)
                await camera.connect()

                Shared.data[camera_hash]['camera'] = camera

        return option

    async def _response(self, *lines):
        """ Reply to client with given params
        """
        reply = 'RTSP/1.0 200 OK\r\n' \
            f'CSeq: {self.cseq}\r\n'

        for row in lines:
            reply += f'{row}\r\n'

        reply += '\r\n'

        self.writer.write(reply.encode())

        Log.print(f'~~~ Client: write\n{reply}')

    def _get_transport_line(self, ask):
        """ Search "interleaved" channels for TCP mode or client ports for UDP one
            Returns "transport" string
        """
        if Config.tcp_mode:
            res = re.match(r'.+?\nTransport:.+?interleaved=(\d-\d)', ask, re.DOTALL)
            channel = res.group(1) if res else '0-1'
            return f'Transport: RTP/AVP/TCP;unicast;interleaved={channel}'

        udp_ports = _get_ports(ask)
        idx = 0 if not self.udp_ports else 1
        self.udp_ports[idx] = udp_ports

        return f'Transport: RTP/AVP;unicast;client_port={udp_ports[0]}-{udp_ports[1]};server_port=5998-5999'

    def _get_description(self):
        """ Create new SDP based on original one from the camera
        """
        sdp = Shared.data[self.camera_hash]['camera'].description
        res = 'v=0\r\n' \
            f'o=- {randrange(100000, 999999)} {randrange(1, 10)} IN IP4 {Config.local_ip}\r\n' \
            's=python-rtsp-server\r\n' \
            't=0 0'
        # 'a=range:npt=0-'

        if not sdp['video']:
            return res
        res += f'\r\nm=video {sdp["video"]["media"]}\r\n' \
            'c=IN IP4 0.0.0.0\r\n' \
            f'b={sdp["video"]["bandwidth"]}\r\n' \
            f'a=rtpmap:{sdp["video"]["rtpmap"]}\r\n' \
            f'a=fmtp:{sdp["video"]["format"]}\r\n' \
            'a=control:track1'

        if not sdp['audio']:
            return res
        res += f'\r\nm=audio {sdp["audio"]["media"]}\r\n' \
            f'a=rtpmap:{sdp["audio"]["rtpmap"]}\r\n' \
            'a=control:track2'
        return res

    async def _check_web_limit(self):
        """ Just drop old "external" connections
        """
        if not Config.web_limit or _get_client_type(self.host) == 'local':
            return
        web_sessions = []
        clients = Shared.data[self.camera_hash]['clients']
        for session_id, client in clients.items():
            if _get_client_type(client.host) == 'web':
                web_sessions.append(session_id)
        if len(web_sessions) > Config.web_limit:
            ws = web_sessions[:-Config.web_limit]
            for session_id in ws:
                Log.write('Client: web limit exceeded, close old connection')
                await clients[session_id].close()


async def _handle(reader, writer):
    """ This callback function will be called every time a connection to the server is made
    """
    client = Client(reader, writer)
    Log.print(f'Client: new connection from {client.host}:{client.tcp_port}')

    while True:
        data = await reader.read(2048)

        if data[0:1] == b'' or writer.transport.is_closing():
            await client.close()
            Log.print(f'Client: connection closed: {client.host}:{client.tcp_port}')
            return

        # Handle client connection
        try:
            if await client.handle(data):  # start TCP mode listening, handling is over
                return
        except Exception as e:
            Log.print(f"Client: error: can't handle request from {client.host}: {e}")
            await client.close()
            return


def _get_session_id(ask):
    """ Search session ID in rtsp ask
    """
    res = re.match(r'.+?\nSession: *([^;\r\n]+)', ask, re.DOTALL)
    if res:
        return res.group(1).strip()

    return ''.join(choices(string.ascii_lowercase + string.digits, k=9))


def _get_cseq(ask):
    """ Search CSeq in rtsp ask
    """
    res = re.match(r'.+?\r\nCSeq: (\d+)', ask, re.DOTALL)
    if not res:
        raise RuntimeError('invalid incoming CSeq')
    return int(res.group(1))


def _get_user_agent(ask):
    """ Search User-Agent in rtsp ask
        [ -~] means any ASCII character from the space to the tilde
    """
    res = re.match(r'.+?\r\nUser-Agent: ([ -~]+)\r\n', ask, re.DOTALL + re.IGNORECASE)
    if not res:
        return 'unknown user agent'
    return res.group(1)


def _get_ports(ask):
    """ Search port numbers in rtsp ask
    """
    res = re.match(r'.+?\nTransport:[^\n]+client_port=(\d+)-(\d+)', ask, re.DOTALL)
    if not res:
        raise RuntimeError('invalid transport ports')
    return [int(res.group(1)), int(res.group(2))]


def _get_client_type(host):
    if host == '127.0.0.1' \
        or host == 'localhost' \
            or (host.startswith('192.168.') and host != Config.local_ip):
        return 'local'
    return 'web'
