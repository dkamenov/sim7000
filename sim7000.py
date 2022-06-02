from machine import UART
from time import sleep, mktime
import re
import gc
import json

class IllegalArgumentException(Exception):
    pass

class SimError(Exception):
    pass

class CmeError(Exception):
    pass

class CmsError(Exception):
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
    def __init__(self,
                timestamp=None,
                lat=None,
                lat_hemisphere=None,
                lon=None,
                lon_hemisphere=None,
                quality=None,
                num_satelites=None,
                hdop=None,
                alt_geoid_height=None,
                alt_unit=None,
                geoidal_separation=None,
                geoidal_separation_unit=None,
                diff_data_age=None,
                diff_ref_station_id=None,):

        (self.timestamp,
        self.lat,
        self.lat_hemisphere,
        self.lon,
        self.lon_hemisphere,
        self.quality,
        self.num_satelites,
        self.hdop,
        self.alt_geoid_height,
        self.alt_unit,
        self.geoidal_separation,
        self.geoidal_separation_unit,
        self.diff_data_age,
        self.diff_ref_station_id,) = (timestamp,
        lat,
        lat_hemisphere,
        lon,
        lon_hemisphere,
        quality,
        num_satelites,
        hdop,
        alt_geoid_height,
        alt_unit,
        geoidal_separation,
        geoidal_separation_unit,
        diff_data_age,
        diff_ref_station_id,)


class Sim7000:
    
    HTTPS_METHODS = {
        'GET': 1,
        'PUT': 2,
        'POST': 3,
        'PATCH': 4,
        'HEAD': 5
    }
    
    def __init__(self, device, baudrate, rx_pin=16, tx_pin=17, apn=None):
        self.apn = apn
        self.uart = UART(device, baudrate, rx=rx_pin, tx=tx_pin, bits=8, parity=None, stop=1, timeout=1000)
        sleep(2)
        self.uart.sendbreak()
        sleep(0.2)        
    
    def cmd(self, cmd):
        result = []
        cmd_prefix=re.match(r'^[A-Z]+', cmd).group(0)
        self.uart.write('AT+' + cmd + '\r')
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
        print(self.cmd('CMEE=2')) # Use verbose error codes
        
        if self.apn:
            print(self.cmd('SAPBR=3,1,"APN","{}"'.format(self.apn))) # network-specific setting
        
        self.cmd('CGDCONT=1,"IP",""') # Configure APN for registration when needed
        
        if not self.is_network_active():
            print(self.cmd('CNACT=1')) #Activate network
    
    def reset(self):
        self.cmd('CFUN=6')
        
    def download_cert(self, file_name):
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
                    print("---------------reading {}b -----------".format(bytes_to_read))
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
    
    def gnss_enable(self, setting):
        self.cmd('CGNSPWR={}'.format(1 if setting else 0))
    
    def _gnss_date_to_time(self, datestr):
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
    
    def get_gnss_fix(self):
        fix = None
        self.cmd('CGNSTST=1,1')
        while True:
            gc.collect()
            line = self.uart.readline()
            if not line:
                break
            line = line.decode('utf-8')
            print('<---{}'.format(line).strip())
            if line.startswith('$GNGGA'):
                fields = line.split('*')[0].split(',')
                if int(fields[6]) == 0: # No fix could be obtained
                    break; 
                fix = GnssFix(
                    timestamp=fields[1],
                    lat = float(fields[2]),
                    lat_hemisphere = fields[3],
                    lon = float(fields[4]),
                    lon_hemisphere = fields[5],
                    quality = int(fields[6]),
                    num_satelites = int(fields[7]),
                    hdop = float(fields[8]),
                    alt_geoid_height = float(fields[9]),
                    alt_unit = fields[10],
                    geoidal_separation = float(fields[11]),
                    geoidal_separation_unit = fields[12],
                    diff_data_age = fields[13],
                    diff_ref_station_id = fields[14],
                                
                    )
                
        return fix
    
    def get_imei(self):
        self.uart.write('AT+GSN\r')
        imei = None
        while True:
            gc.collect()
            line = self.uart.readline()
            if line == None:
                break
            
            l = line.decode('utf-8').strip()
            print('<---{}'.format(l))
            if l.startswith('AT+GSN') or l == '':
                continue
            if l.startswith('OK'):
                return imei
            imei = l
            
    def get_gsm_time_utc(self):
        '''
        format is "yy/MM/dd,hh:mm:ss±zz", where characters indicate
        year (two last digits),month, day, hour, minutes, seconds and time zone
        (indicates the difference, expressed in quarters of an hour, between the
        local time and GMT; range -47...+48). E.g. 6th of May 2010, 00:01:52
        GMT+2 hours equals to "10/05/06,00:01:52+08".
        '''
        resp = self.cmd('CCLK?')
        if len(resp) != 1 or not resp[0].startswith('+CCLK:') or '"' not in resp[0]:
            return None
        datestr = resp[0].split('"')[1]
        year = 2000 + int(datestr[0:2])
        month = int(datestr[3:5])
        day = int(datestr[6:8])
        hour = int(datestr[9:11])
        minutes = int(datestr[12:14])
        seconds = int(datestr[15:17])
        tz_q = int(datestr[17:20])
        return mktime((year, month, day, hour, minutes, seconds, None, None)) - tz_q * 15 * 60

