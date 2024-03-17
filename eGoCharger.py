
from enum import Enum
import json
import time
import logging


import paho.mqtt.client as pahoMqtt

from PythonLib.JsonUtil import JsonUtil
from PythonLib.Mqtt import MQTTHandler, Mqtt
from PythonLib.Scheduler import Scheduler
from PythonLib.DateUtil import DateTimeUtilities
from PythonLib.TaskQueue import TaskQueue

logger = logging.getLogger('eGoCharger')

# https://github.com/goecharger/go-eCharger-API-v2/blob/main/apikeys-de.md


class GoEchargerCarStatus(Enum):
    Unknown = 0
    Idle = 1
    Charging = 2
    WaitCar = 3
    Complete = 4
    Error = 4


class Module:
    def __init__(self) -> None:
        self.scheduler = Scheduler()
        self.taskQueue = TaskQueue()
        self.mqttClient = Mqtt("koserver.iot", "/house/agents/eGoCharger", pahoMqtt.Client("eGoCharger"))

    def getScheduler(self) -> Scheduler:
        return self.scheduler

    def getMqttClient(self) -> Mqtt:
        return self.mqttClient

    def getTaskQueue(self) -> TaskQueue:
        return self.taskQueue

    def setup(self) -> None:
        self.scheduler.scheduleEach(self.mqttClient.loop, 500)

    def loop(self) -> None:
        self.scheduler.loop()
        self.taskQueue.loop()


class eGoCharger:
    def __init__(self, module: Module) -> None:
        self.mqttClient = module.getMqttClient()
        self.scheduler = module.getScheduler()
        self.taskQueue = module.getTaskQueue()

    def setup(self) -> None:

        # wh	R	double	Status	energy in Wh since car connected
        self.mqttClient.subscribeIndependentTopic('/house/garage/go-eCharger/226305/wh', self.__receiveWh)

        # eto	R	uint64	Status	energy_total, measured in Wh
        self.mqttClient.subscribeIndependentTopic('/house/garage/go-eCharger/226305/eto', self.__receiveEto)

        # rbc	R	uint32	Status	reboot_counter
        self.mqttClient.subscribeIndependentTopic('/house/garage/go-eCharger/226305/rbc', self.__receiveRbc)

        # alw	R	bool	Status	Is the car allowed to charge at all now?
        self.mqttClient.subscribeIndependentTopic('/house/garage/go-eCharger/226305/alw', self.__receiveAlw)

        # nrg	R	array	Status	energy array, U (L1, L2, L3, N), I (L1, L2, L3), P (L1, L2, L3, N, Total), pf (L1, L2, L3, N)
        self.mqttClient.subscribeIndependentTopic('/house/garage/go-eCharger/226305/nrg', self.__receiveNrg)

        # car	R	optional<uint8>	Status	carState, null if internal error (Unknown/Error=0, Idle=1, Charging=2, WaitCar=3, Complete=4, Error=5)
        self.mqttClient.subscribeIndependentTopic('/house/garage/go-eCharger/226305/car', self.__receiveCar)

        # psm	R/W	uint8	Config	phaseSwitchMode (Auto=0, Force_1=1, Force_3=2)
        self.mqttClient.subscribeIndependentTopic('/house/garage/go-eCharger/226305/psm', self.__receivePsm)
        self.mqttClient.subscribe('control/PhaseSwitchMode[Auto,Force_1,Force_3]', self.__setPsm)

        # frc	R/W	uint8	Config	forceState (Neutral=0, Off=1, On=2)
        self.mqttClient.subscribeIndependentTopic('/house/garage/go-eCharger/226305/frc', self.__receiveFrc)
        self.mqttClient.subscribe('control/ForceState[Neutral,Off,On]', self.__setFrc)

        # dwo	R/W	optional<double>	Config	charging energy limit, measured in Wh, null means disabled, not the next-trip energy
        self.mqttClient.subscribeIndependentTopic('/house/garage/go-eCharger/226305/dwo', self.__receiveDwo)
        self.mqttClient.subscribe('control/NextTrip[On,Off]', self.__setNextTrip)

        self.__keepAlive()

        self.scheduler.scheduleEach(self.__keepAlive, 10000)

    def __keepAlive(self) -> None:
        self.mqttClient.publishIndependentTopic('/house/agents/eGoCharger/heartbeat', DateTimeUtilities.getCurrentDateString())
        self.mqttClient.publishIndependentTopic('/house/agents/eGoCharger/subscriptions', JsonUtil.obj2Json(self.mqttClient.getSubscriptionCatalog()))

    def __receiveWh(self, payload: str) -> None:
        self.mqttClient.publish("data/WhSinceCarConnected", payload)

    def __receiveEto(self, payload: str) -> None:
        self.mqttClient.publish("data/EnergyTotalInWh", payload)

    def __receiveRbc(self, payload: str) -> None:
        self.mqttClient.publish("data/RebootCtr", payload)

    def __receiveAlw(self, payload: str) -> None:
        self.mqttClient.publish("data/IsCarAllowedToCharge", payload)

    def __receiveNrg(self, payload: str) -> None:
        try:
            jsonVar = json.loads(payload)

            self.mqttClient.publish("data/PowerChargingL1", jsonVar[7])
            self.mqttClient.publish("data/PowerChargingL2", jsonVar[8])
            self.mqttClient.publish("data/PowerChargingL3", jsonVar[9])
            self.mqttClient.publish("data/PowerChargingN", jsonVar[10])
            self.mqttClient.publish("data/PowerChargingTotal", jsonVar[11])
        except BaseException:
            logging.exception('')

    def __receiveCar(self, payload: str) -> None:
        status = GoEchargerCarStatus(int(payload))

        self.mqttClient.publish("data/StatusAsNumber", payload)
        self.mqttClient.publish("data/Status", status.name)

    def __receivePsm(self, payload: str) -> None:
        self.mqttClient.publish("data/PhaseSwitchModeAsNumber", payload)
        match(payload):
            case '0':
                self.mqttClient.publish("data/PhaseSwitchMode", "Auto")
            case '1':
                self.mqttClient.publish("data/PhaseSwitchMode", "Force_1")
            case '2':
                self.mqttClient.publish("data/PhaseSwitchMode", "Force_3")
            case _:
                self.mqttClient.publish("data/PhaseSwitchMode", "Unknown")

    def __setPsm(self, payload: str) -> None:

        match(payload):
            case 'Auto':
                self.mqttClient.publishIndependentTopic("/house/garage/go-eCharger/226305/psm/set", "0")
            case 'Force_1':
                self.mqttClient.publishIndependentTopic("/house/garage/go-eCharger/226305/psm/set", "1")
            case 'Force_3':
                self.mqttClient.publishIndependentTopic("/house/garage/go-eCharger/226305/psm/set", "3")
            case _:
                pass

    def __receiveFrc(self, payload: str) -> None:
        self.mqttClient.publish("data/ForceStateAsNumber", payload)
        match(payload):
            case '0':
                self.mqttClient.publish("data/ForceState", "Neutral")
            case '1':
                self.mqttClient.publish("data/ForceState", "Off")
            case '2':
                self.mqttClient.publish("data/ForceState", "On")
            case _:
                self.mqttClient.publish("data/ForceState", "Unknown")

    def __setFrc(self, payload: str) -> None:

        match(payload):
            case 'Neutral':
                self.mqttClient.publishIndependentTopic("/house/garage/go-eCharger/226305/frc/set", "0")
            case 'Off':
                self.mqttClient.publishIndependentTopic("/house/garage/go-eCharger/226305/frc/set", "1")
            case 'On':
                self.mqttClient.publishIndependentTopic("/house/garage/go-eCharger/226305/frc/set", "2")
            case _:
                pass

    def __receiveDwo(self, payload: str) -> None:
        self.mqttClient.publish("data/ChargingEnergyLimitIfNextTrip", payload)
        match(payload):
            case 'null':
                self.mqttClient.publish("data/NextTrip", "Off")
            case _:
                self.mqttClient.publish("data/NextTrip", "On")

    def __setNextTrip(self, payload: str) -> None:

        match(payload):
            case 'On':
                pass
            case 'Off':
                self.mqttClient.publishIndependentTopic('/house/garage/go-eCharger/226305/dwo/set', 'null')


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logging.getLogger('eGoCharger').setLevel(logging.DEBUG)

    module = Module()
    module.setup()

    logging.getLogger('eGoCharger').addHandler(MQTTHandler(module.getMqttClient(), '/house/agents/eGoCharger/log'))

    eGoCharger(module).setup()

    print("eGoCharger is running")

    while (True):
        module.loop()
        time.sleep(0.25)


if __name__ == '__main__':
    main()
