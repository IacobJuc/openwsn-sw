import logging

class NullHandler(logging.Handler):
    def emit(self, record):
        pass
log = logging.getLogger('moteProbeSerialThread')
log.setLevel(logging.ERROR)
log.addHandler(NullHandler())

import threading
import serial
import time
import struct
import traceback
import sys

import OpenHdlc
from moteConnector import OpenParser
import openvisualizer_utils as u

from pydispatch import dispatcher

class moteProbeSerialThread(threading.Thread):

    def __init__(self,serialportName,serialportBaudrate):
        
        # log
        log.debug("create instance")
        
        # store params
        self.serialportName       = serialportName
        self.serialportBaudrate   = serialportBaudrate
        
        # local variables
        self.hdlc                 = OpenHdlc.OpenHdlc()
        self.lastRxByte           = self.hdlc.HDLC_FLAG
        self.busyReceiving        = False
        self.inputBuf             = ''
        self.outputBuf            = []
        self.outputBufLock        = threading.RLock()
        
        # initialize the parent class
        threading.Thread.__init__(self)
        
        # give this thread a name
        self.name                 = 'moteProbeSerialThread@'+self.serialportName
       
        # connect to dispatcher
        dispatcher.connect(
            self._bufferDataToSend,
            signal = 'fromMoteConnector@'+self.serialportName,
        )
    
    def run(self):
        try:
            # log
            log.debug("start running")
        
            while True:     # open serial port
                log.debug("open serial port {0}@{1}".format(self.serialportName,self.serialportBaudrate))
                self.serial = serial.Serial(self.serialportName,self.serialportBaudrate)
                while True: # read bytes from serial port
                    try:
                        rxByte = self.serial.read(1)
                    except Exception as err:
                        log.warning(err)
                        time.sleep(1)
                        break
                    else:
                        if      (
                                    (not self.busyReceiving)             and 
                                    self.lastRxByte==self.hdlc.HDLC_FLAG and
                                    rxByte!=self.hdlc.HDLC_FLAG
                                ):
                            # start of frame
                            log.debug("{0}: start of hdlc frame {1} {2}".format(self.name, u.formatStringBuf(self.hdlc.HDLC_FLAG), u.formatStringBuf(rxByte)))
                            self.busyReceiving       = True
                            self.inputBuf            = self.hdlc.HDLC_FLAG
                            self.inputBuf           += rxByte
                        elif    (
                                    self.busyReceiving                   and
                                    rxByte!=self.hdlc.HDLC_FLAG
                                ):
                            # middle of frame
                            
                            self.inputBuf           += rxByte
                        elif    (
                                    self.busyReceiving                   and
                                    rxByte==self.hdlc.HDLC_FLAG
                                ):
                            # end of frame
                            log.debug("{0}: end of hdlc frame {1} ".format(self.name, u.formatStringBuf(rxByte)))
                            self.busyReceiving       = False
                            self.inputBuf           += rxByte
                            
                            try:
                                self.inputBuf        = self.hdlc.dehdlcify(self.inputBuf)
                            except OpenHdlc.HdlcException as err:
                                log.warning('{0}: invalid serial frame: {0}'.format(self.name,err))
                            else:
                                if self.inputBuf==chr(OpenParser.OpenParser.SERFRAME_MOTE2PC_REQUEST):
                                      with self.outputBufLock:
                                        if self.outputBuf:
                                            outputToWrite = self.outputBuf.pop(0)
                                            self.serial.write(outputToWrite)
                                else:
                                    # dispatch
                                    dispatcher.send(
                                        sender        = self.name,
                                        signal        = 'fromProbeSerial@'+self.serialportName,
                                        data          = self.inputBuf[:],
                                    )
                        
                        self.lastRxByte = rxByte
        except Exception as err:
            errMsg=u.formatCrashMessage(self.name,err)
            print errMsg
            log.critical(errMsg)
            sys.exit(1)
        
    #======================== public ==========================================
    
    #======================== private =========================================
    
    def _bufferDataToSend(self,data):
        
        # frame with HDLC
        hdlcData = self.hdlc.hdlcify(data)
        
        # add to outputBuf
        with self.outputBufLock:
            self.outputBuf += [hdlcData]
