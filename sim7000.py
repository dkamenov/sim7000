from machine import UART
from time import sleep
import re


class IllegalArgumentException(Exception):
    pass

class SimError(Exception):
    pass

class CmeError(Exception):
    pass

class CmsError(Exception):
    pass

class Sim7000:
    def __init__(self, device, baudrate, rx_pin=16, tx_pin=17):
        self.uart = UART(device, baudrate, rx=rx_pin, tx=tx_pin, bits=8, parity=None, stop=1, timeout=1000)
        sleep(2)
        self.uart.sendbreak()
        sleep(0.2)        
    
    def cmd(self, cmd):
        result = []
        cmd_prefix=re.match(r'^[A-Z]+', cmd).group(0)
        self.uart.write('AT+' + cmd + '\r')
        while True:
            l = self.uart.readline().decode('utf-8').rstrip()
            print('->' + l)
            if l.startswith(cmd) or not l:
                continue
            if l.startswith('OK'):
                return result
            if l.startswith('ERROR'):
                raise SimError(l)
            if l.startswith('+CME ERROR:'):
                raise CmeError(l.split(':')[1].strip())
            if l.startswith('+' + cmd_prefix):
                result.append(l)        
        
    def query(self, cmd):
        r = self.cmd(cmd)
        results = self._parse_result(r[0]) ## TODO: is this the correct response line? - check if command matches
        return results
        
    def _parse_result(self, l):
        str_vals = l.split(':')[1].split(',')
        return [eval(x.strip()) for x in str_vals]
    
    def wait_for(self, cmd):
        ''' Waits for response from cmd and returns parsed result '''
        while True:
            buf = self.uart.readline()
            if not buf:
                print('#', end='')
                continue
            
            l = buf.decode('utf-8').rstrip()
            print('->' + l)
            if l.startswith('+' + cmd):
                return self._parse_result(l)
        
    def get_bearer_status(self, cid=1):
        r = self.query('SAPBR=2,{}'.format(cid))
        return r[1] if r[0] == cid else None

    def get_bearer_ip(self, cid=1):
        r = self.query('SAPBR=2,{}'.format(cid))
        return r[2] if r[0] == cid else None

    def open_bearer(self, cid=1):
        self.cmd('SAPBR=1,{}'.format(cid))
        
    def close_bearer(self, cid=1):
        self.cmd('SAPBR=0,{}'.format(cid)) 
        
    def set_bearer_param(self, cid=1, param_name="", param_value=""):
        if not param_name:
            raise IllegalArgumentException('param_name must be defined')
        self.cmd('SAPBR=3,{},"{}","{}"'.format(cid, param_name, param_value))     
    
    def ping(self):
        try:
            self.uart.write('AT\r')
            while True:
                buf = self.uart.readline()
                if not buf:
                    return False
                l = buf.decode('utf-8').rstrip()
                print('->' + l)
                if l.startswith('OK'):
                    return True
                if not l:
                    return False
        except:
            return False
        
    def get_pin_status(self):
        try:
            r = self.cmd('CPIN?')
            if r[0].startswith('+CPIN:'):
                return r[0].split(':')[1].strip()
            return None
        except SimError:
            return None
        
    def init_network(self):
        print(self.cmd('CMEE=2')) # Use verbose error codes
        #print(self.cmd('COPS?'))  # Query Network information, operator and network mode
        #print(self.cmd('SAPBR=?'))
        #print(self.cmd('SAPBR=3,1,"APN","tfdata"')) # Specific for StraightTalk/ATT
        bs = self.get_bearer_status()
        if bs != 1:
            self.open_bearer()
            self.set_bearer_param(param_name="APN", param_value="tfdata")
        
        print("PIN Status: " + self.get_pin_status())
        
        print(self.cmd('CGDCONT=1,"IP",""')) # Configure APN for registration when needed
        print(self.cmd('CGNAPN')) # Query the APN delivered by the network after the CAT-M or NB-IOT network is successfully registered.
        
        r = self.cmd('CNACT?')
        status, ip_addr = self._parse_result(r[0])
        print("Network status: ", status)
        if int(status) == 0: 
            print(self.cmd('CNACT=1')) #Activate network
            sleep(5)
            r = self.cmd('CNACT?')    
    
    def reset(self):
        self.cmd('CFUN=6')
    
    def http_get(self, url):
        try:
            print(self.cmd('HTTPTERM'))
        except:
            print('exception clearing HTTP state')
        
        #if url.startswith('https:'):
        #    self.cmd('CSSLCFG="sslversion",1,3')
        
        self.cmd('HTTPINIT')
        self.cmd('HTTPPARA="CID",1')
        self.cmd('HTTPPARA="URL","{}"'.format(url))
        self.cmd('HTTPACTION=0')
        #self.cmd('HTTPSTATUS=?')
        method, status, response_len = self.wait_for('HTTPACTION')
        #self.cmd('HTTPSTATUS=?')
        self.cmd('HTTPREAD')
        self.cmd('HTTPTERM')
    