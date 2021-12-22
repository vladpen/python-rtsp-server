import socket


class Config:
    rtsp_port = 4554
    start_udp_port = 5550
    local_ip = socket.gethostbyname(socket.gethostname())

    # Camera(s) settings.
    #    * The keys of this dictionary will be called "camera hash".
    #    * "storage_command" must contains two pairs of parentheses (for URL and output file name).
    #       Examples:
    #           ffmpeg -i {} -c copy {}.avi
    #           mencoder {} -ovc copy -o {}.avi
    #           openRTSP -b 10000000 -i -w 1920 -h 1080 -f 15 {} > {}.avi
    #       Note that these utilities aren't included an must be installed yourself.
    #    * "storage_save_from_camera". You can save the stream from camera directly, as well as from this server.
    #
    cameras = {
        'some-URL-compatible-string/including-UTF-characters': {
            'path': 'some folder in the storage_path',
            'url': 'rtsp://<login>:<password>@<host>:554/<uri>',
            'storage_command': 'any *nix command for saving rtsp stream to a file',
            'storage_save_from_camera': True},
    }

    # Force UDP or TCP protocol globally
    tcp_mode = False

    # Limit connections from the web. Set to 0 for unlimit connections
    web_limit = 2

    # Check UDP traffic from cameras, secs
    watchdog_interval = 30

    # Run this script with root permissions or change this path and set up log rotation yourself
    log_file = '/var/log/python-rtsp-server.log'

    # Attention!
    # All files and subdirectories older than "storage_period_days" in this folder will be deleted!
    storage_path = 'absolute path to video monitoring storage folder'
    storage_fragment_secs = 600
    storage_period_days = 14
    storage_enable = False

    debug = True
