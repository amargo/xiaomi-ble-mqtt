#!/usr/bin/python3

from lywsd02 import Lywsd02Client as Client
from mitemp.mitemp_bt.mitemp_bt_poller import MiTempBtPoller
from mitemp.mitemp_bt.mitemp_bt_poller import MI_TEMPERATURE, MI_HUMIDITY, MI_BATTERY
from btlewrap.bluepy import BluepyBackend
from bluepy.btle import BTLEException
import paho.mqtt.publish as publish
import traceback
import configparser
import os
import json
import datetime
import enum

class Sensor(enum.Enum): 
    lywsd02 = "lywsd02"
    other = "other"

workdir = os.path.dirname(os.path.realpath(__file__))
config = configparser.ConfigParser()
config.read("{0}/devices.ini".format(workdir))

devices = config.sections()

# Averages
averages = configparser.ConfigParser()
averages.read("{0}/averages.ini".format(workdir))

messages = []

for device in devices:

    mac = config[device].get("device_mac")
    sensor_type = config[device].get("sensor_type").lower()
    # Configure the client.
    if sensor_type == Sensor.lywsd02.name:
        client = Client(mac, data_request_timeout=config[device].getint("timeout", 10))
    else:
        poller = MiTempBtPoller(mac, BluepyBackend, ble_timeout=config[device].getint("timeout", 10))

    try:        
        # if sensor_type is Sensor.lywsd02:
        if sensor_type == Sensor.lywsd02.name:
            temperature = client.temperature
            humidity = client.humidity
            battery = client.battery
        else:
            temperature = poller.parameter_value(MI_TEMPERATURE)
            humidity = poller.parameter_value(MI_HUMIDITY)
            battery = poller.parameter_value(MI_BATTERY)            

        data = json.dumps({
            "temperature": temperature,
            "humidity": humidity,
            "battery": battery
        })

        # Check averages
        avg = []
        average_count = config[device].getint("average")
        if average_count:
            if mac in averages.sections():
                avg = json.loads(averages[mac]["avg"])

            # Add average
            avg.insert(0, data)

            # Strip data
            avg = avg[0:average_count]

            # Calc averages
            temperature = 0
            humidity = 0
            battery = 0

            for a in avg:
                al = json.loads(a)
                temperature += al["temperature"]
                humidity += al["humidity"]
                battery += al["battery"]

            temperature = round(temperature / len(avg), 1)
            humidity = round(humidity / len(avg), 1)
            battery = round(battery / len(avg), 1)

            # Convert averages
            averages[mac] = {}
            averages[mac]["avg"] = json.dumps(avg)

            # Rewrite data
            data = json.dumps({
                "temperature": temperature,
                "humidity": humidity,
                "battery": int(battery),
                "average": len(avg)
            })

        print(datetime.datetime.now(), device, " : ", data)
        messages.append({'topic': config[device].get("topic"), 'payload': data, 'retain': config[device].getboolean("retain", False)})
        availability = 'online'
    except BTLEException as e:
        availability = 'offline'
        print(datetime.datetime.now(), "Error connecting to device {0}: {1}".format(device, str(e)))
    except Exception as e:
        availability = 'offline'
        print(datetime.datetime.now(), "Error polling device {0}. Device might be unreachable or offline.".format(device))
        # print(traceback.print_exc())
    finally:
        messages.append({'topic': config[device].get("availability_topic"), 'payload': availability, 'retain': config[device].getboolean("retain", False)})

# Init MQTT
mqtt_config = configparser.ConfigParser()
mqtt_config.read("{0}/mqtt.ini".format(workdir))
mqtt_broker_cfg = mqtt_config["broker"]

try:
    auth = None
    mqtt_username = mqtt_broker_cfg.get("username")
    mqtt_password = mqtt_broker_cfg.get("password")

    if mqtt_username:
        auth = {"username": mqtt_username, "password": mqtt_password}

    publish.multiple(messages, hostname=mqtt_broker_cfg.get("host"), port=mqtt_broker_cfg.getint("port"), client_id=mqtt_broker_cfg.get("client"), auth=auth)
except Exception as ex:
    print(datetime.datetime.now(), "Error publishing to MQTT: {0}".format(str(ex)))

with open("{0}/averages.ini".format(workdir), "w") as averages_file:
    averages.write(averages_file)
