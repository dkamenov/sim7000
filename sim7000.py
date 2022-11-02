from machine import UART
from time import sleep, mktime
import re
import gc
import json

def _safe_float(val):
    s = val.strip()
    return float(s) if s else None

def _safe_int(val):
    s = val.strip()
    return int(s) if s else None

class IllegalArgumentException(Exception):
    pass

class SimError(Exception):
    pass

class CmeError(Exception):
    pass

class CmsError(Exception):
    pass

class ValidationError(Exception):
    pass

class HttpResponse:
    
    def __init__(self, content=None, status_code=None, content_len=None, method=None):
        self.content=content
        self.content_len=content_len
        self.status_code=status_code
        self.method=method
    
    def text(self):
        return self.content.decode('utf-8')
    
    def json(self):
        return json.loads(self.content.decode('utf-8'))


class GnssFix:
    def __init__(self):
        self.gnss_run_status = None #1 GNSS run status
        self.fix_status = None      #2 Fix status -- 0-1 1
        self.utc_datetime = None    #3 UTC date & Time
        self.lat = None             #4 Latitude ±dd.dddddd [-90.000000,90.000000] 10
        self.lon = None             #5 Longitude ±ddd.dddddd [-180.000000,180.000000] 11
        self.altitude = None         #6 MSL Altitude meters
        self.speed_over_ground = None          #7 Speed Over Ground Km/hour [0,999.99] 6
        self.course_over_ground = None #8 Course Over Ground degrees [0,360.00] 6
        self.fix_mode = None #9 Fix Mode -- 0,1,2 [1] 1
        #self.reserved1 = None #10 Reserved1 
        self.hdop = None #11 HDOP -- [0,99.9] 4 (Horizontal Dilution of Precision)
        self.pdop = None #12 PDOP -- [0,99.9] 4 (Position Dilution of Precision)
        self.vdop = None #13 VDOP -- [0,99.9] 4 (Vertical Dilution of Precision)
        #14 Reserved2
        self.gps_sats_in_view = None  #15 GPS Satellites in View -- [0,99] 2
        self.gnss_sats_used = None #16 GNSS Satellites Used -- [0,99] 2
        self.glonass_sats_in_view = None #17 GLONASS Satellites in View -- [0,99] 2
        #18 Reserved3 
        self.cn0_max = None #19 C/N0 max dBHz [0,55] 
        self.hpa = None #20 HPA [2] meters [0,9999.9] (Horizontal Position Accuracy)
        self.vpa = None #21 VPA [2] meters [0,9999.9] (Vertical Position Accuracy)
    
    def _gnss_date_to_time(datestr):
        ''' convert a string in GNSS format (yyyyMMddhhmmss.sss) to a native MicroPython time, ignoring milliseconds '''
        if len(datestr) != 18 or datestr[14] != '.':
            return None
        
        year = int(datestr[0:4])
        month = int(datestr[4:6])
        day = int(datestr[6:8])
        hour = int(datestr[8:10])
        minutes = int(datestr[10:12])
        seconds = int(datestr[12:14])
        return mktime((year, month, day, hour, minutes, seconds, None, None))
    
    def fromCSV(data):
        if not data.startswith('+CGNSINF'):
            raise ValidationError('Incorrect prefix')
        fields = data[9:].strip().split(',')
        
        if not _safe_int(fields[0]) or not _safe_int(fields[1]): # No GNSS run or no fix
            return None
        
        f = GnssFix()
        f.gnss_run_status = _safe_int(fields[0]) #1 GNSS run status
        f.fix_status = _safe_int(fields[1])      #2 Fix status -- 0-1 1
        f.utc_datetime = GnssFix._gnss_date_to_time(fields[2])    #3 UTC date & Time
        f.lat = _safe_float(fields[3])             #4 Latitude ±dd.dddddd [-90.000000,90.000000] 10
        f.lon = _safe_float(fields[4])             #5 Longitude ±ddd.dddddd [-180.000000,180.000000] 11
        f.altitude = _safe_float(fields[5])         #6 MSL Altitude meters
        f.speed_over_ground = _safe_float(fields[6])          #7 Speed Over Ground Km/hour [0,999.99] 6
        f.course_over_ground = _safe_float(fields[7]) #8 Course Over Ground degrees [0,360.00] 6
        f.fix_mode = _safe_int(fields[8]) #9 Fix Mode -- 0,1,2 [1] 1
        #10 Reserved1 
        f.hdop = _safe_float(fields[10]) #11 HDOP -- [0,99.9] 4
        f.pdop = _safe_float(fields[11]) #12 PDOP -- [0,99.9] 4
        f.vdop = _safe_float(fields[12]) #13 VDOP -- [0,99.9] 4
         #14 Reserved2
        f.gps_sats_in_view = _safe_int(fields[14]) #15 GPS Satellites in View -- [0,99] 2
        f.gnss_sats_used = _safe_int(fields[15])   #16 GNSS Satellites Used -- [0,99] 2
        f.glonass_sats_in_view = _safe_int(fields[16])  #17 GLONASS Satellites in View -- [0,99] 2
        #18 Reserved3 
        f.cn0_max = _safe_int(fields[18])  #19 C/N0 max dBHz [0,55] 
        f.hpa = _safe_float(fields[19])  #20 HPA [2] meters [0,9999.9] 
        f.vpa = _safe_float(fields[20])  #21 VPA [2] meters [0,9999.9]
        return f



class Sim7000:
    
    HTTPS_METHODS = {
        'GET': 1,
        'PUT': 2,
        'POST': 3,
        'PATCH': 4,
        'HEAD': 5
    }
    
    def __init__(self, device, baudrate, rx_pin, tx_pin, apn=None):
        self.apn = apn
        self.uart = UART(device, baudrate, rx=rx_pin, tx=tx_pin, bits=8, parity=None, stop=1, timeout=1000)
        sleep(1)
        self.uart.sendbreak()
        sleep(0.2)        
    
    def _normalize_command(self, cmd):
        return ('AT+' if not cmd.startswith('AT') else '') + cmd + '\r'
    
    def cmd(self, cmd):
        result = []
        cmd_prefix=re.match(r'^[A-Z]+', cmd).group(0)
        self.uart.write(self._normalize_command(cmd))
        while True:
            buf = self.uart.readline()
            if not buf:
                continue
            l = buf.decode('utf-8').rstrip()
            print('<---' + l)
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
        return [eval(x.strip()) if x else None for x in str_vals]
    
    def wait_for(self, cmd):
        ''' Waits for response from cmd and returns parsed result '''
        while True:
            buf = self.uart.readline()
            if not buf:
                print('#', end='')
                continue
            
            l = buf.decode('utf-8').rstrip()
            print('<---' + l)
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
        ''' check if device is alive '''
        try:
            self.uart.write('AT\r')
            while True:
                buf = self.uart.readline()
                if not buf:
                    return False
                l = buf.decode('utf-8').rstrip()
                print('<---' + l)
                if l.startswith('OK'):
                    return True
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
        
    def is_gprs_active(self):
        r = self.query('CGATT?')
        return r[0] == 1
    
    def get_network_apn(self):
        ''' Query APN delivered by the network '''
        r = self.query('CGNAPN')
        return r[1] if r[0] == 1 else None 

    def get_network_info(self):
        return self.query('COPS?')
    
    def is_network_active(self):
        return self.query('CNACT?')[0] == 1
    
    def get_network_ip(self):
        return self.query('CNACT?')[1]
      
        
    def init_network(self):
        self.cmd('CMEE=2') # Use verbose error codes
        
        if self.apn:
            self.cmd('SAPBR=3,1,"APN","{}"'.format(self.apn)) # Access Point Name (network-specific setting)
        
        self.cmd('CGDCONT=1,"IP",""') # Configure APN for registration when needed
        
        if not self.is_network_active():
            print(self.cmd('CNACT=1')) #Activate network
    
    def reset(self):
        ''' soft-reset sim7000 board '''
        self.cmd('CFUN=6')
        
    def download_cert(self, file_name):
        ''' Download root CA certificate to device in order to use for HTTPS certificate verification '''
        f=open('cacerts/{}'.format(file_name), 'r')
        cert = f.read()
        size = len(cert)
        f.close()
        self.cmd('CFSINIT')
        self.uart.write('AT+CFSWFILE=3,"{}",0,{},1000\r'.format(file_name, size)) # 3-file system, 1000 - timeout (ms)
        print("download command sent, waiting for confirm")
        while True:
            buf = self.uart.readline()
            if not buf:
                print('#', end='')
                continue
            
            l = buf.decode('utf-8').rstrip()
            print('<---' + l)
            if l.startswith('DOWNLOAD'):
                break

        print("Sending file...")
        bytes_written = self.uart.write(cert)
        print("Wrote {} bytes".format(bytes_written))
        self.uart.write('\r')
        self.cmd('CFSTERM')
        self.cmd('CSSLCFG="convert",2,"{}"'.format(file_name)) 
        
    
    def _get_host(self, url):
        return url.split('/')[2]

    def http(self, url, method='GET', body=None, headers={}, root_ca_cert=None):
        
        if self.query('SHSTATE?')[0] != 0: # Terminate previous connection if open
            self.cmd('SHDISC')
        
        if url.startswith('https:'):
            self.cmd('CSSLCFG="sslversion",1,3')
            if root_ca_cert:
                self.cmd('SHSSL=1,"{}"'.format(root_ca_cert))
            else:
                self.cmd('SHSSL=1,""') # !!! Need to set empty cert as #1 in order to skip cert validation!!

        host = self._get_host(url)
        # Mandatory params:
        schema = url.split(':')[0]
        self.cmd('SHCONF="URL","{}://{}"'.format(schema, host))
        self.cmd('SHCONF="BODYLEN",1024')
        self.cmd('SHCONF="HEADERLEN",350')
        
        if body:
            self.cmd('SHBOD="{}",{}'.format(body.replace('"', r'\"'), len(body)))

        self.cmd('SHCONN')
        for header_name, header_val in headers.items():
            self.cmd('SHAHEAD="{}","{}"'.format(header_name, header_val))

        method_code = Sim7000.HTTPS_METHODS[method.upper()]

        query_string = url.split(host)[1]
        if not query_string:
            query_string = '/'
            
        self.cmd('SHREQ="{}",{}'.format(query_string, method_code))
        method, status, response_len = self.wait_for('SHREQ')
        
        resp = HttpResponse(content_len=response_len, content=b'', method=method, status_code=status)
        if status <= 599:
            while len(resp.content) < response_len:
                self.cmd('SHREAD={},{}'.format(len(resp.content), response_len-len(resp.content)))            
                while True:
                    gc.collect()
                    buf = self.uart.readline()
                    if not buf:
                        break
                    line = buf.decode('utf-8').rstrip()
                    if not line.startswith('+SHREAD:'):
                        print('<---{}'.format(line))
                        continue
                    bytes_to_read = self._parse_result(line)[0]
                    print("--------------- reading {}b -----------".format(bytes_to_read))
                    buf = self.uart.read(bytes_to_read)
                    resp.content += buf
                    print("--------------- {} of {}b read so far -----------".format(len(buf), len(resp.content)))
                    if len(buf) < bytes_to_read:
                        break

                    if len(resp.content) >= response_len:
                        print("--------------- A total of {}b were read ------------".format(len(resp.content)))
                        break
                                
        self.cmd('SHDISC')
        gc.collect()
        return resp
    
    def ip_ping(self, addr, count=1, packetsize=64, interval=1000):
        return self.cmd('SNPING4="{}",{},{},{}'.format(addr, count, packetsize, interval))
    
    def gnss_enable(self, setting=True):
        ''' Turn GNSS chip on/off
            setting - True / False
        '''
        self.cmd('CGNSPWR={}'.format(1 if setting else 0))
        
    def is_gnss_on(self):
        ''' Check if GNSS is powered on '''
        return self.query('CGNSPWR?')[0] == 1
    
    def get_gnss_fix(self):
        response = self.cmd('CGNSINF')
        return GnssFix.fromCSV(response[0]) if response else None
    
    def cmd_collect(self, cmd):
        cmd = self._normalize_command(cmd)
        self.uart.write(cmd)
        output = []
        while True:
            line = self.uart.readline()
            if line == None:
                continue   
            l = line.decode('utf-8').strip()
            print('<---{}'.format(l))
            if not l or l.startswith(cmd.strip()):
                continue
            if line.startswith('OK'):
                return output
            output.append(l)
        
    def get_imei(self):
        ''' Request Terminal Adapter (TA) serial number identification (IMEI) '''
        return self.cmd_collect('GSN')[0]
    
    def get_iccid(self):
        ''' Request device ICC ID '''
        return self.cmd_collect('CCID')[0]
    
    def get_flash_device_type(self):
        ''' Request Terminal Adapter (TA) serial number identification (IMEI) '''
        return self.cmd_collect('CDEVICE?')
    
    def get_product_info(self):
        ''' Display Product Identification Information '''
        return self.cmd_collect('GSV')
    
    def get_gsm_time_utc(self):
        ''' time from local clock synchronized from network - may fail if no wireless connection '''
        resp = self.cmd('CCLK?')
        if len(resp) != 1 or not resp[0].startswith('+CCLK:') or '"' not in resp[0]:
            return None
        '''
        format is "yy/MM/dd,hh:mm:ss±zz", where characters indicate
        year (two last digits),month, day, hour, minutes, seconds and time zone
        (indicates the difference, expressed in quarters of an hour, between the
        local time and GMT; range -47...+48). E.g. 6th of May 2010, 00:01:52
        GMT+2 hours equals to "10/05/06,00:01:52+08".
        '''
        datestr = resp[0].split('"')[1]
        year = 2000 + int(datestr[0:2])
        month = int(datestr[3:5])
        day = int(datestr[6:8])
        hour = int(datestr[9:11])
        minutes = int(datestr[12:14])
        seconds = int(datestr[15:17])
        tz_q = int(datestr[17:20])
        return mktime((year, month, day, hour, minutes, seconds, None, None)) - tz_q * 15 * 60

