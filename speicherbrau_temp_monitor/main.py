#!/usr/bin/python
# -*- coding: utf-8 -*-
import logging
import os.path
from datetime import datetime, timedelta
from random import uniform
from time import time, mktime

import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, QtGui
from PyQt5.QtWidgets import QMainWindow
from pyqtgraph.graphicsItems.PlotCurveItem import PlotCurveItem
sensors = list()
sensor2Name = None


level = logging.INFO
logger = logging.getLogger()
logger.setLevel(level)
ch = logging.StreamHandler()
ch.setLevel(level)
formatter = logging.Formatter('%(asctime)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)
W1ThermSensor = None


def mockSensors():
	class W1ThermSensor:
		def __init__(self, uid, start, stop):
			self.id = uid
			self.start = start
			self.stop = stop

		def get_temperature(self):
			return uniform(self.start, self.stop)

	sensor2Name = {
		0: "Maischkessel",
		1: "Nachguss",
		2: "Würzepfanne"
	}

	for i in range(3):
		logger.debug("used class as sensor: %r", W1ThermSensor)
		sensors.append(W1ThermSensor(sensor2Name[i], i * 20 + 20, i * 20 + 20 + 20))

try:
	from w1thermsensor import W1ThermSensor
	sensors = W1ThermSensor.get_available_sensors()
except Exception as err:
	logger.exception(err)
	logger.info("Now mocking our sensors. Perhaps you should check if modules are loaded or sensors are plugged in")


if not sensors:
	mockSensors()


qtapp = QtGui.QApplication([])


class TimeAxisItem(pg.AxisItem):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

	def tickStrings(self, values, scale, spacing):
		return [datetime.fromtimestamp(value).strftime("%H:%M:%S") for value in values]


class SensorsThread(QtCore.QThread):
	newSensorData = QtCore.pyqtSignal(dict)

	def __init__(self, ticking, parent=None):
		super(SensorsThread, self).__init__(parent)
		self.ticking = ticking

	def run(self):
		while 1:
			stamp = time()
			sensorsData = dict()
			for sensor in sensors:
				tempInCelsius = sensor.get_temperature()
				# logger.info("Sensor %s has temperature %.2f", sensor.id, tempInCelsius)
				sensorsData[sensor.id] = (stamp, tempInCelsius)
			self.newSensorData.emit(sensorsData)
			self.sleep(self.ticking)


class Sensor(object):
	def __init__(self, ix: int, sensor: W1ThermSensor, num_data: int, graphicsWindow: pg.GraphicsWindow, parent):
		# logger.info("Sensor: %r, %r, %r, %r", ix, sensor, num_data, graphicsWindow)
		self.parentWidget = parent
		self.sensor = sensor
		self.name = sensor.id
		self.num_data = num_data
		self.data = np.array([float('inf')] * self.num_data, dtype=np.float)
		self.timestamps = np.array([float('inf')] * self.num_data, dtype=np.float)
		initialTime = datetime.now()
		for i in range(num_data):
			self.timestamps[-i] = mktime((initialTime - timedelta(seconds=i * parent.ticking)).timetuple())
			# logger.info("temp index: %r, %r", -i, datetime.fromtimestamp(self.timestamps[-i]))

		graphPen = pg.mkPen(color="r", width=2)
		axisPen = pg.mkPen(color="w", width=2)
		self.plotItem = PlotCurveItem(pen=graphPen, width=4, name=self.name)
		self.xAxis = TimeAxisItem(pen=axisPen, orientation='bottom')
		self.font = QtGui.QFont("Helvetica", 18, 18)
		self.xAxis.setStyle(tickTextHeight=30, tickFont=self.font)
		self.plot = graphicsWindow.addPlot(row=ix, col=0, axisItems={'bottom': self.xAxis})
		self.label = self.plot.titleLabel
		self.label.setAttr("color", "w")
		self.label.setAttr("bold", True)
		self.label.setAttr("size", "18pt")
		self.plot.getAxis("left").setPen(axisPen)
		self.plot.getAxis("left").setStyle(tickTextHeight=30, tickFont=self.font)
		self.plot.addItem(self.plotItem)
		self.plot.setMouseEnabled(x=True, y=False)
		self.plot.buttonsHidden = True
		self.plot.enableAutoRange("xy", False)
		self.plot.setYRange(0, 105, False, False)
		# logger.info("%r, %r", datetime.fromtimestamp(self.timestamps[-(self.num_data - 105)]),
		#             datetime.fromtimestamp(self.timestamps[-1]))
		self.plot.setXRange(self.timestamps[-105], self.timestamps[-1])
		self.plot.showGrid(True, True, 1)
		if ix > 0:
			self.plot.setXLink(parent.sensorsList[ix - 1].plot)
		self.plot.vb.sigRangeChangedManually.connect(self.viewChanged)

	def add_values(self, timestamp, value):
		self.data = np.roll(self.data, -1)
		self.timestamps = np.roll(self.timestamps, -1)
		self.data[self.num_data - 1] = value
		self.timestamps[self.num_data - 1] = timestamp
		self.plotItem.setData(self.timestamps, self.data)
		self.plot.setTitle("{0} - {1:.02f} °C".format(self.name, self.data[self.num_data - 1]))
		logger.info("scrolling: %r", self.parentWidget.scrolling)
		if self.parentWidget.scrolling:
			self.plot.setXRange(self.timestamps[-105], self.timestamps[-1])

	def viewChanged(self, a):
		data = self.plot.vb.state['viewRange'][0]
		leftClamp = datetime.fromtimestamp(data[0])
		rightClamp = datetime.fromtimestamp(data[1])
		initialTime = datetime.now()
		diff = initialTime-rightClamp
		result = diff < timedelta(seconds=5)
		self.parentWidget.scrolling = result
		logger.info("calc should scrolling: %r, %r, %r, %r",  rightClamp, initialTime, diff, result)


class SpeicherbrauPlotterWidget(QMainWindow):
	def __init__(self, parent=None):
		QMainWindow.__init__(self, parent)
		self.graphicsWindow = pg.GraphicsWindow("Speicherbrau Plotter")
		self.setCentralWidget(self.graphicsWindow)
		self.resize(1920, 1080)
		self.activeSensors = list()
		self.num_data = 5760
		self.sensorsList = list()
		self.sensorsById = dict()
		self.scrolling = True
		self.ticking = 1.0
		self.leftClamp = None
		self.rightClamp = None

		for ix, sensor in enumerate(sensors):
			sensorEntry = Sensor(ix, sensor, self.num_data, self.graphicsWindow, self)
			self.sensorsList.append(sensorEntry)
			self.sensorsById[sensor.id] = sensorEntry

		self.thread = SensorsThread(self.ticking)
		self.thread.newSensorData.connect(self.updateData)
		self.thread.start(QtCore.QThread.IdlePriority)

	def pubdir(self):
		return os.path.dirname(os.path.abspath(__file__))

	def active_actor_count(self):
		return self.max_actors

	@QtCore.pyqtSlot(dict)
	def updateData(self, sensorData):
		for sensorId, (stamp, temp) in sensorData.items():
			self.sensorsById[sensorId].add_values(stamp, temp)


def main():
	window = SpeicherbrauPlotterWidget()
	window.setWindowTitle("Speicherbräu Temperatur")
	window.show()
	qtapp.exec_()


if __name__ == '__main__':
	main()
