#!/usr/bin/env python3

import sys
assert sys.version_info >= (3, 0)

import re
import asyncio
import time
from datetime import datetime
from datetime import timezone

from astropy.coordinates import EarthLocation,SkyCoord
from astropy.time import Time
from astropy import units as u
from astropy.coordinates import AltAz


####### Observer location (latitude, longitude)

lat = 44.42
lon = 5.12


#######

polaris_ip = '192.168.0.1'
polaris_port = 9090
local_port = 10001

LOGGING = True
LOG518 = False
DEBUG = True


####### Polaris

response_queues = {}
polaris_current_mode = -1
polaris_msg_re = re.compile('^(\d\d\d)@([^#]*)#')

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

    elif cmd == "519":
        arg_dict = polaris_parse_args(args)
        if cmd in response_queues:
            response_queues[cmd].put_nowait(arg_dict)

    else:
        if DEBUG and (cmd != "518" or LOG518):
            print(f"<<< Polaris: unmatched command {cmd} received")


async def polaris_start_stop_tracking(writer, tracking):
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

def decode_stellarium_packet(s):
    t = int.from_bytes(s[4:11], byteorder='little')

    ra = int.from_bytes(s[12:16], byteorder='little')
    dec = int.from_bytes(s[16:20], byteorder='little', signed=True)

    ra = (24*ra)/0x100000000
    dec = (90*dec)/0x40000000

    observing_location = EarthLocation(lat=lat, lon=lon)  
    observing_time = Time(datetime.fromtimestamp(t/1E6, tz=timezone.utc), format='datetime')
    aa = AltAz(location=observing_location, obstime=observing_time)

    coord = SkyCoord(ra, dec, unit=(u.hour, u.deg)) 
    altAz = coord.transform_to(aa)
    if LOGGING:
        print(f"<<< Stellarium: {observing_time} RA: {int(coord.ra.hms.h)}h{int(coord.ra.hms.m)}mn{coord.ra.hms.s:.5f}s Dec: {coord.dec.deg:.5f}° -> Az.: {altAz.az.deg:.5f}° Alt.: {altAz.alt.deg:.5f}° ")
    return (altAz.az.deg, altAz.alt.deg)


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

async def main():
    global response_queues

    try:
        server_reader, server_writer = await asyncio.open_connection(polaris_ip, polaris_port)
    except Exception as e:
        print(f"Failed to connect to server: {e}")
        return

    local_server = await asyncio.start_server(lambda reader, writer: handle_local_input(server_writer, reader, writer), 'localhost', local_port)

    tasks = [
        client_reader(server_reader),
        polaris_init(server_writer)
    ]

    async with local_server:
        await asyncio.gather(*tasks)

try:
    asyncio.run(main())
except ValueError as value:
    print(f"{value}\nQuit.")
except Exception as error:
    print("Error {error}, quit.")
except KeyboardInterrupt as kb:
    print("Keyboard interrupt.")
