#!/usr/bin/env python3

import sys
assert sys.version_info >= (3, 0)

import os
import getopt
import re
import asyncio
import time
from datetime import datetime
from datetime import timezone
from math import pi

# https://rhodesmill.org/pyephem
import ephem

####### Globals

lat = None
lon = None

polaris_ip = '192.168.0.1'
polaris_port = 9090
local_port = 10001

LOGGING = False
LOG518 = False
DEBUG = False
TESTS = False


####### Polaris

response_queues = {}
polaris_current_mode = -1
polaris_msg_re = re.compile("^(\d\d\d)@([^#]*)#")

async def polaris_send_msg(writer, msg):
    if DEBUG:
        print(f">>> Polaris: msg: {msg}")
    writer.write(msg.encode())
    await writer.drain()

def polaris_parse_msg(msg):
    m = polaris_msg_re.match(msg)
    if m:
        return (msg[len(m.group(0)):],m.group(1), m.group(2))
    else:
        return False

def polaris_parse_args(args_str):
    # chop the last ";" and split
    args = args_str[:-1].split(";")
    arg_dict = {}
    for arg in args:
        (name, value) = arg.split(":")
        arg_dict[name] = value
    return arg_dict

def polaris_parse_cmd(cmd, args):
    global response_queues
    if cmd == "284":
        arg_dict = polaris_parse_args(args)
        polaris_current_mode = int(arg_dict['mode'])
        if DEBUG:
            print(f"<<< Polaris: current mode is {polaris_current_mode}")
        if cmd in response_queues:
            response_queues[cmd].put_nowait(arg_dict)

    elif cmd == "518":
        None

    elif cmd == "519":
        arg_dict = polaris_parse_args(args)
        if DEBUG:
            print(f"<<< Polaris: response to command 'goto' ({cmd}) received")
        if cmd in response_queues:
            response_queues[cmd].put_nowait(arg_dict)

    else:
        if DEBUG and (cmd != "518" or LOG518):
            print(f"<<< Polaris: response to command {cmd} received")


async def polaris_start_stop_tracking(writer, tracking):
    """
    polaris_start_stop_tracking is used to start or stop tracking

    :param writer: is used to send commands to the Polaris
    :param tracking: if 1 start tracking at star rotation speed, 0 don't track
    """
    if tracking:
        if LOGGING:
            print(">>> Polaris: Start tracking")
        state = 1
    else:
        if LOGGING:
            print(">>> Polaris: Stop tracking")
        state = 0
    await polaris_send_msg(writer, f"1&531&3&state:{state};speed:0;#")


async def polaris_goto(writer, az, alt, tracking):
    """
    polaris_goto is used to turn the head to point in (az, alt) direction.

    :param writer: is used to send commands to the Polaris
    :param az: is the azimuth to point, 0° < az < 360°
    :param alt: is the altitude to point, -90° < alt < 90° (but the Polaris is hardware limited)
    :param tracking: if 1 start tracking at star rotation speed, 0 don't track
    """
    
    global response_queues
    await polaris_start_stop_tracking(writer, False)

    if tracking:
        track = 1
    else:
        track = 0

    # azimuth az should be transformed before being sent to the Polaris -180° < polaris_az < 180°
    polaris_az = 360 - az if az>180 else -az
    cmd = '519'
    msg = f"1&{cmd}&3&state:1;yaw:{polaris_az:.5f};pitch:{alt:.5f};lat:{lat:.5f};track:{track};speed:0;lng:{lon:.5f};#"
    if LOGGING:
        print(f">>> Polaris: Goto Az.:{az:.5f} Alt.:{alt:.5f}")
    response_queues[cmd] = asyncio.Queue()
    await polaris_send_msg(writer, msg)
    ret_dict = await response_queues[cmd].get()
    
    if DEBUG:
        print(f"<<< Polaris: result for cmd: {cmd} {ret_dict}")

    if 'ret' in ret_dict:
        goto_result = int(ret_dict['ret'])
        if goto_result == 1:
            ret_dict = await response_queues[cmd].get()
            if DEBUG:
                print(f"<<< Polaris: 2nd result for cmd: {cmd} {ret_dict}")

    del response_queues[cmd]
    return ret_dict


async def polaris_move(writer, az_axis, alt_axis, astro_axis, time):
    """
    polaris_move is used to turn the head around the Azm and Alt axis at some speed
    and duration a fixed amount of time.

    :param writer: is used to send commands to the Polaris
    :param az_axis: rotation speed around the Azm axis between -5 and 5
    :param alt_axis: rotation speed around the Alt axis between -5 and 5
    :param astro_axis: rotation speed around the Astro axis between -5 and 5
    :param time: duration of the rotation in seconds
    """
    global response_queues
    cmd_az = '532'
    cmd_alt = '533'
    cmd_astro = '534'
    
    if az_axis != 0:
        if az_axis > 0:
            level = az_axis if az_axis <= 5 else 5
            msg = f"1&{cmd_az}&3&key:0;state:1;level:{level};#"
        else:
            level = -az_axis if az_axis >= -5 else 5
            msg = f"1&{cmd_az}&3&key:1;state:1;level:{level};#"
        await polaris_send_msg(writer, msg)

    if alt_axis != 0:
        if alt_axis > 0:
            level = alt_axis if alt_axis <= 5 else 5
            msg = f"1&{cmd_alt}&3&key:0;state:1;level:{level};#"
        else:
            level = -alt_axis if alt_axis >= -5 else 5
            msg = f"1&{cmd_alt}&3&key:1;state:1;level:{level};#"
        await polaris_send_msg(writer, msg)

    if astro_axis != 0:
        if astro_axis > 0:
            level = astro_axis if astro_axis <= 5 else 5
            msg = f"1&{cmd_astro}&3&key:0;state:1;level:{level};#"
        else:
            level = -astro_axis if astro_axis >= -5 else 5
            msg = f"1&{cmd_astro}&3&key:1;state:1;level:{level};#"
        await polaris_send_msg(writer, msg)

    await asyncio.sleep(time)

    if az_axis != 0:
        if az_axis > 0:
            level = az_axis if az_axis <= 5 else 5
            msg = f"1&{cmd_az}&3&key:0;state:0;level:{level};#"
        else:
            level = -az_axis if az_axis >= -5 else 5
            msg = f"1&{cmd_az}&3&key:1;state:0;level:{level};#"
        await polaris_send_msg(writer, msg)

    if alt_axis != 0:
        if alt_axis > 0:
            level = alt_axis if alt_axis <= 5 else 5
            msg = f"1&{cmd_alt}&3&key:0;state:0;level:{level};#"
        else:
            level = -alt_axis if alt_axis >= -5 else 5
            msg = f"1&{cmd_alt}&3&key:1;state:0;level:{level};#"
        await polaris_send_msg(writer, msg)

    if astro_axis != 0:
        if astro_axis > 0:
            level = astro_axis if astro_axis <= 5 else 5
            msg = f"1&{cmd_astro}&3&key:0;state:0;level:{level};#"
        else:
            level = -astro_axis if astro_axis >= -5 else 5
            msg = f"1&{cmd_astro}&3&key:1;state:0;level:{level};#"
        await polaris_send_msg(writer, msg)


async def polaris_stop_move(writer):
    """
    polaris_move is used to stop the rotation on both Azm, Alt and Astro axis.

    :param writer: is used to send commands to the Polaris
    """
    
    global response_queues
    cmd_az = '532'
    cmd_alt = '533'
    cmd_astro = '534'

    level = 0
    msg = f"1&{cmd_az}&3&key:0;state:0;level:{level};#"
    await polaris_send_msg(writer, msg)

    msg = f"1&{cmd_alt}&3&key:1;state:0;level:{level};#"
    await polaris_send_msg(writer, msg)
    
    msg = f"1&{cmd_astro}&3&key:1;state:0;level:{level};#"
    await polaris_send_msg(writer, msg)


async def polaris_test_move(writer):
    global response_queues
    await asyncio.sleep(10)
    
    # speed of the rotation 1 (slowest) ... 5 (fastest)
    speed = 5
    # duration of the rotation in seconds
    duration = 20
    
    print("Polaris testing move commands...")
    print("Stop tracking...")
    await polaris_start_stop_tracking(writer, 0)
    print("Move on az axis...")
    await polaris_move(writer, speed, 0, 0, duration)
    await asyncio.sleep(3)
    print("Move in opposite direction on az axis...")
    await polaris_move(writer, -speed, 0, 0, duration)
    await asyncio.sleep(3)
    print("Move on alt axis...")
    await polaris_move(writer, 0, speed, 0, duration)
    await asyncio.sleep(3)
    print("Move in opposite direction on alt axis...")
    await polaris_move(writer, 0, -speed, 0, duration)
    await asyncio.sleep(3)
    print("Move on astro axis...")
    await polaris_move(writer, 0, 0, speed, duration)
    await asyncio.sleep(3)
    print("Move in opposite direction on astro axis...")
    await polaris_move(writer, 0, 0, -speed, duration)
    await asyncio.sleep(3)
    print("Move on both axis...")
    await polaris_move(writer, speed, speed, speed, duration)
    await asyncio.sleep(3)
    print("Move in opposite direction on both axis...")
    await polaris_move(writer, -speed, -speed, -speed, duration)
    await asyncio.sleep(3)
    print("Stop moving...")
    await polaris_stop_move(writer)
    await asyncio.sleep(1)
    print ("End testing move commands")


async def polaris_reset_rotation(writer, az_axis, alt_axis, astro_axis):
    """
    polaris_reset_rotation is used to reset the rotation around the 3 axis,
    going home position

    :param writer: is used to send commands to the Polaris
    :param az_axis: if true reset the Azm axis
    :param alt_axis: if true reset the Alt axis
    :param astro_axis: if true reset the Astro axis
    """
    cmd = '523'
    if az_axis:
        msg = f"1&523&3&axis:1;#"
        await polaris_send_msg(writer, msg)
        
    if alt_axis:
        msg = f"1&523&3&axis:2;#"
        await polaris_send_msg(writer, msg)
    
    if astro_axis:
        msg = f"1&523&3&axis:3;#"
        await polaris_send_msg(writer, msg)
    

async def polaris_test_reset_rotation(writer):
    await asyncio.sleep(10)
    print("Reset rotation on az axis...")
    await polaris_reset_rotation(writer, True, 0, 0)
    await asyncio.sleep(5)
    print("Reset rotation on alt axis...")
    await polaris_reset_rotation(writer, 0, True, 0)
    await asyncio.sleep(5)
    print("Reset rotation on astro axis...")
    await polaris_reset_rotation(writer, 0, 0, True)


async def polaris_new_alignment(writer, az, alt):
    """
    polaris_new_alignment is used to do a new celestial alignment with star at (az,alt)

    :param writer: is used to send commands to the Polaris
    :param az: the azimut of the star used for celestial alignment
    :param alt: the altitude of the star used for celestial alignment
    """
    global lat, lon
    
    # goto (az,alt), stop tracking
    await polaris_goto(writer, az, alt, 0)
    
    # celestial alignment step 1
    polaris_az = 360 - az if az>180 else -az
    cmd = '530'
    msg = f"1&{cmd}&3&step:1;yaw:{polaris_az};pitch:{alt};lat:{lat};num:1;lng:{lon};#"
    await polaris_send_msg(writer, msg)
    
    await asyncio.sleep(15) # delay to align the star in the iPhone app

    # celestial alignment step 2 (validation)
    msg = f"1&{cmd}&3&step:2;yaw:{polaris_az};pitch:{alt};lat:{lat};num:1;lng:{lon};#"
    await polaris_send_msg(writer, msg)


async def polaris_test_new_alignment(writer):
    await asyncio.sleep(10)
    print("New celestial position alignement...")
    await polaris_new_alignment(writer, 120, 45)


async def polaris_get_current_mode(writer):
    global response_queues
    cmd = '284'
    msg = f"1&{cmd}&2&-1#"
    response_queues[cmd] = asyncio.Queue()
    await polaris_send_msg(writer, msg)
    ret_dict = await response_queues[cmd].get()
    del response_queues[cmd]
    if DEBUG:
        print(f"<<< Polaris: result for cmd: {cmd} {ret_dict}")
    return ret_dict


async def polaris_init(writer):
    global response_queues
    print("Polaris communication init...")
    ret_dict = await polaris_get_current_mode(writer)
    if  'mode' in ret_dict and int(ret_dict['mode']) == 8:
        if 'track' in ret_dict and int(ret_dict['track']) == 3:
            raise ValueError('Polaris is in astro mode but not properly setup, please finish the astro mode setup with the mobile app.')
        print("Polaris communication init... done")
    else:
        raise ValueError('Polaris is not in astro mode, please use the mobile app to setup the astro mode.')


####### Stellarium

def dec2dms(dd):
   is_positive = dd >= 0
   dd = abs(dd)
   minutes,seconds = divmod(dd*3600,60)
   degrees,minutes = divmod(minutes,60)
   degrees = degrees if is_positive else -degrees
   return f"{int(degrees)}:{int(minutes)}:{seconds:.2f}"

def dms2dec(dms):
    (degree, minute, second, frac_seconds) = re.split('\D+', dms, maxsplit=4)
    return int(degree) + float(minute) / 60 + float(second) / 3600 + float(frac_seconds) / 360000

def decode_stellarium_packet(s):
    t = int.from_bytes(s[4:11], byteorder='little')

    ra = int.from_bytes(s[12:16], byteorder='little')
    dec = int.from_bytes(s[16:20], byteorder='little', signed=True)

    ra = (24*ra)/0x100000000
    dec = (90*dec)/0x40000000

    if DEBUG:
        print(f"<<< Stellarium: t={t} ra={ra} dec={dec}")

    observer = ephem.Observer()
    observer.long = dec2dms(lon)
    observer.lat = dec2dms(lat)
    observer.elevation = 0
    observer.pressure = 0 # no refraction correction.
    observer.epoch = ephem.J2000
    observer.date = ephem.Date(datetime.fromtimestamp(t/1E6, tz=timezone.utc))

    if DEBUG:
        print(f"<<< Stellarium: Observer location lat={observer.lat} lon={observer.lon}")

    target = ephem.FixedBody()
    target._ra = dec2dms(ra)
    target._dec = dec2dms(dec)
    target._epoch = ephem.J2000
    target.compute(observer)
    if LOGGING:
        print(f"<<< Stellarium: Date: {observer.date} UT RA: {target.ra} Dec: {target.dec} -> Az.: {target.az} Alt.: {target.alt}")
    return (dms2dec(str(target.az)), dms2dec(str(target.alt)))


####### network

async def client_reader(reader):
    global response_queues
    buffer = ""
    while True:
        data = await reader.read(256)
        if not data:
            break
        buffer += data.decode()
        parse_result = polaris_parse_msg(buffer)
        if parse_result:
            buffer = parse_result[0]
            cmd = parse_result[1]
            if LOGGING and (cmd != "518" or LOG518):
                print(f"<<< Polaris: {cmd}@{parse_result[2]}#")
            polaris_parse_cmd(cmd, parse_result[2])

async def handle_local_input(server_writer, reader, writer):
    while True:
        data = await reader.read(256)
        if not data:
            break
        (az, alt) = decode_stellarium_packet(data)
        if DEBUG:
            print(f"<<< Stellarium: {':'.join(('0'+hex(x)[2:])[-2:] for x in data)}")
        ret_dict = await polaris_goto(server_writer, az, alt, True)
        if 'ret' in ret_dict:
            goto_result = int(ret_dict['ret'])
            if goto_result == -1:
                print(f"Goto Az.: {az} Alt.: {alt} failed")

async def main(argv):
    global LOGGING, LOG518, DEBUG, TESTS
    global response_queues
    global lat, lon

    usage = f"{os.path.basename(sys.argv[0])} [-dfhlLt]--lat <latitude> --lon <longitude>"
    try:
        opts, args = getopt.getopt(argv,"dhlLt",["lat=","lon="])
    except getopt.GetoptError:
        print (usage)
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print (usage)
            sys.exit()
        elif opt == "--lat":
            lat = float(arg)
        elif opt == "--lon":
            lon = float(arg)
        elif opt == "-l":
            LOGGING = True
        elif opt == "-L":
            LOGGING = True
            LOG518 = True
        elif opt == "-d":
            DEBUG = True
        elif opt == "-t":
            TESTS = True
    
    if lat == None or lon == None:
        print(usage)
        sys.exit(2)

    print (f"Current location: latitude={lat} longitude={lon}")

    if LOG518:
        print("Full logging is on")
    elif LOGGING:
        print("Logging is on")

    if DEBUG:
        print("Debug is on")

    try:
        server_reader, server_writer = await asyncio.open_connection(polaris_ip, polaris_port)
    except Exception as e:
        print(f"Failed to connect to server: {e}")
        return

    local_server = await asyncio.start_server(lambda reader, writer: handle_local_input(server_writer, reader, writer), 'localhost', local_port)

    tasks = [
        client_reader(server_reader),
        polaris_init(server_writer),
    ]
    
    if TESTS:
#        tasks.append(polaris_test_move(server_writer))
#        tasks.append(polaris_test_reset_rotation(server_writer))
        tasks.append(polaris_test_new_alignment(server_writer))

    async with local_server:
        await asyncio.gather(*tasks)


#######

if __name__ == "__main__":
    try:
        asyncio.run(main(sys.argv[1:]))
    except ValueError as value:
        print(f"{value}\nQuit.")
    except Exception as error:
        print(f"Error {error}, quit.")
    except KeyboardInterrupt as kb:
        print("Keyboard interrupt.")
