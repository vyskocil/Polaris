# Polaris
Polaris electric tripod head communication protocol, interface between Stellarium application and Polaris.

## Polaris communication protocol

The Polaris is listening on TCP/IP at the address 192.168.0.1 on port 9090 on the WIFI access point it generate.
The communication between Polaris and the client app is based on alphanumeric messages. 
Here is a exchange sample when the client application switch the Polaris to Photo mode :

| Client application commands | Polaris responses|
| ------------------ | ------- |
| 1&285&2&mode:1;#   |         |
| 1&520&2&state:0;#  |         |
| 1&531&3&state:0;speed:0;# |  |
| 1&524&3&-1#        |         |  
|								| 285@mode:1;ret:0;# |
|								| 520@ret:0;#524@state:1;# |
| 1&284&2&-1#        |         |
|								| 284@mode:1;state:0;# |
| 1&517&3&-1#        |          |
| 1&545&2&-1#        |          |
| 								| 517@yaw:-0.129433;pitch:0.007093;roll:0.019947;# |
|								| 545@dir:0;# |

To be continued...

## polaris_stellarium.py

This python script is working as a interface between [Stellarium](https://stellarium.org/) the free open source planetarium and the Polaris head that allow easily pointing the sky objects with the Polaris using the Stellarium interface.

### Installation

The script needs Python version 3.0 or better and the astropy python library that could be installed using `pip` or `pip3`:

```pip install astropy```

It needs the current location on earth, this should be set in the `polaris_stellarium.py` script, with the `lat=...` and `lon=...` declarations.

### Stellarium setting up

In the `Plugins` tab of the `Configuration` interface the `Telescope Control` plugin should be `Load at startup`. After a relaunch of Stellarium a new button is added to the bottom menubar that allow to configure and control telescope, it can be opened using `Command-0`. In the configuration windows a new telescope of kind `External software or a remote computer` should be added.

### Running 

You should power-up the Polaris and use the mobile app to setup it as usual in Astro mode, then you'll need to connect the computer on the Polaris WIFI.
Then you may launch the `polaris_stellarium.py` in the terminal and see some output like the following:

```
Polaris communication init...
>>> Polaris: msg: 1&284&2&-1#
<<< Polaris: 284@mode:8;state:0;track:0;speed:0;halfSpeed:0;remNum:;runTime:;photoNum:;#
<<< Polaris: current mode is 8
<<< Polaris: result for cmd: 284 {'mode': '8', 'state': '0', 'track': '0', 'speed': '0', 'halfSpeed': '0', 'remNum': '', 'runTime': '', 'photoNum': ''}
Polaris communication init... done
```

Then you may use Stellarium to pilot the Polaris !
You should `Connect` the telescope you added in the Stellarium setting up phase, then you may use the telescope controle interface.


