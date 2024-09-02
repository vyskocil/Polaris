#!/usr/bin/env python3

import sys
assert sys.version_info >= (3, 0)

import os
import getopt
import re
import asyncio
import time
import requests
from datetime import datetime
from datetime import timezone
from math import pi

# https://rhodesmill.org/pyephem
import ephem

####### Globals

local_port = 10001

alpaca_server = '127.0.0.1'
alpaca_port = 5555
alpaca_client_id = 65432
alpaca_transaction_id = 123

LOGGING = False
DEBUG = False
TESTS = False

####### Alpaca

def alpaca_goto(ra, dec):
    rest_cmd = '/api/v1/telescope/0/slewtocoordinatesasync'
    url = 'http://' + alpaca_server + ':' + str(alpaca_port) + rest_cmd
    payload = {'ClientTransactionID' : str(alpaca_transaction_id) , 'ClientID' : str(alpaca_client_id), 'RightAscension' : str(ra), 'Declination' : str(dec) }
    if LOGGING:
        print(f">>> Alpaca: {url}: {payload}")
    
    try:
        r = requests.put(url, data=payload)
        if DEBUG:
            print(f"alpaca_goto ra={ra} decl={dec} http status code={r.status_code} response={r.content}")
    
    except Exception as error:
        print(f"Error {error}")
    
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

    observer = ephem.Observer()
    observer.long = dec2dms(lon)
    observer.lat = dec2dms(lat)
    observer.elevation = 0
    observer.pressure = 0 # no refraction correction.
    observer.epoch = ephem.J2000
    observer.date = ephem.Date(datetime.fromtimestamp(t/1E6, tz=timezone.utc))

    if DEBUG:
        print(f"<<< Stellarium: Observer location lat={observer.lat} lon={observer.lon}")
        print(f"<<< Stellarium: t={t} ra={ra} dec={dec}")
    
    return (ra, dec)

####### main loop

async def mainloop():
    while True:
        await asyncio.sleep(1)

####### network

async def handle_local_input(reader, writer):
    while True:
        data = await reader.read(256)
        if not data:
            break
        if DEBUG:
            print(f"<<< Stellarium: {':'.join(('0'+hex(x)[2:])[-2:] for x in data)}")
        (ra, dec) = decode_stellarium_packet(data)
        alpaca_goto(ra, dec)

async def main(argv):
    global LOGGING, DEBUG, TESTS
    global local_port
    global alpaca_port

    usage = f"{os.path.basename(sys.argv[0])} [-dhl]  --StellariumPort <Stellarium port> --AlpacaPort <Alpca port>"
    try:
        opts, args = getopt.getopt(argv,"dhl",["StellariumPort=", "AlpacaPort="])
    except getopt.GetoptError:
        print (usage)
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print (usage)
            sys.exit()
        elif opt == "--StellariumPort":
            local_port = int(arg)
        elif opt == "--AlpcaPort":
            alpaca_port = int(arg)
        elif opt == "-l":
            LOGGING = True
        elif opt == "-d":
            DEBUG = True
    
    print (f"Stellarium port={local_port}")
    print (f"Alpaca port={alpaca_port}")

    if LOGGING:
        print("Logging is on")

    if DEBUG:
        print("Debug is on")

    local_server = await asyncio.start_server(lambda reader, writer: handle_local_input(reader, writer), 'localhost', local_port)

    tasks = [
        mainloop()
    ]
    
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
