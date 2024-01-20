#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#     ||          ____  _ __
#  +------+      / __ )(_) /_______________ _____  ___
#  | 0xBC |     / __  / / __/ ___/ ___/ __ `/_  / / _ \
#  +------+    / /_/ / / /_/ /__/ /  / /_/ / / /_/  __/
#   ||  ||    /_____/_/\__/\___/_/   \__,_/ /___/\___/
#
#  Copyright (C) 2011-2013 Bitcraze AB
#
#  Crazyflie Nano Quadcopter Client
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Crazyflie radio bootloader for flashing firmware.
"""
import binascii
import logging
import math
import struct
import time

import cflib.crtp
from .boottypes import Target
from .boottypes import TargetTypes
from .boottypes import BootVersion
from cflib.crtp.crtpstack import CRTPPacket

__author__ = 'Bitcraze AB'
__all__ = ['Cloader']

logger = logging.getLogger(__name__)


class Cloader:
    """Bootloader utility for the Crazyflie"""

    def __init__(self, link, info_cb=None, in_boot_cb=None):
        print("Cloader: __init__")
        """Init the communication class by starting to communicate with the
        link given. clink is the link address used after resetting to the
        bootloader.

        The device is actually considered in firmware mode.
        """
        self.link = None
        self.uri = link
        self.in_loader = False

        self.page_size = 0
        self.buffer_pages = 0
        self.flash_pages = 0
        self.start_page = 0
        self.cpuid = 'N/A'
        self.error_code = 0
        self.protocol_version = 0xFF

        self._info_cb = info_cb
        self._in_boot_cb = in_boot_cb

        self.targets = {}
        self.mapping = None
        self._available_boot_uri = ('radio://0/110/2M/E7E7E7E7E7', 'radio://0/0/2M/E7E7E7E7E7')

        self.progress = {}

    def close(self):
        print("Cloader: close")
        """ Close the link """
        if self.link:
            self.link.close()

    def scan_for_bootloader(self):
        print("Cloader: scan_for_bootloader start")

        link = cflib.crtp.get_link_driver('radio://0/80/2M/E7E7E7E7E7')
        ts = time.time()
        res = ()
        while len(res) == 0 and (time.time() - ts) < 10:
            res = link.scan_selected(self._available_boot_uri)

        link.close()

        
        if len(res) > 0:
            print("Cloader: scan_for_bootloader get res",end=':')
            print(res)
            print("Cloader: scan_for_bootloader end")
            return res[0]
        print("Cloader: scan_for_bootloader end")
        return None

    def reset_to_bootloader(self, target_id: int) -> bool:
        print("Cloader: reset_to_bootloader"+str(target_id))

        pk = CRTPPacket(0xFF, [target_id, 0xFF])
        self.link.send_packet(pk)
        address = None

        timeout = 5  # seconds
        ts = time.time()
        while time.time() - ts < timeout:
            pk = self.link.receive_packet(2)
            if pk is None:
                continue
            if pk.port == 15 and pk.channel == 3 and len(pk.data) > 3:
                if struct.unpack('<BB', pk.data[0:2]) != (target_id, 0xFF):
                    continue

                address = 'B1' + binascii.hexlify(pk.data[2:6][::-1]).upper().decode('utf8')

                pk = CRTPPacket(0xFF, [target_id, 0xF0, 0x00])
                self.link.send_packet(pk)
                time.sleep(0.5)

                self.link.close()
                self.link = cflib.crtp.get_link_driver(f'radio://0/0/2M/{address}?safelink=0')
                time.sleep(0.5)
                return True

        return False

    def reset_to_firmware(self, target_id: int) -> bool:
        print("Cloader: reset_to_firmware"+str(target_id))
        
        """ Reset to firmware
        The parameter target_id corresponds to the device to reset.

        Return True if the reset has been done, False on timeout
        """
        pk = CRTPPacket(0xFF, [target_id, 0xFF])
        self.link.send_packet(pk)

        timeout = 5  # seconds
        ts = time.time()
        while time.time() - ts < timeout:
            answer = self.link.receive_packet(2)
            print(answer)
            if answer is None:
                self.link.send_packet(pk)
                continue
            if answer.port == 15 and answer.channel == 3 and len(answer.data) > 2:
                if struct.unpack('<BB', pk.data[0:2]) != (target_id, 0xFF):
                    continue
                pk = CRTPPacket(0xff, [target_id, 0xf0, 0x01])
                self.link.send_packet(pk)
                time.sleep(1)
                return True

        time.sleep(0.1)
        return False

    def open_bootloader_uri(self, uri=None):
        print("Cloader: open_bootloader_uri")

        if self.link:
            self.link.close()
        if uri:
            self.link = cflib.crtp.get_link_driver(uri + '?safelink=0')
        else:
            self.link = cflib.crtp.get_link_driver(
                self.clink_address + '?safelink=0')

    def check_link_and_get_info(self, target_id=0xFF):
        print("Cloader: check_link_and_get_info:"+str(target_id))
        """Try to get a connection with the bootloader ...
           update_info has a timeout of 10 seconds """
        if self._update_info_stm32_alt(target_id):
            if self._in_boot_cb:
                self._in_boot_cb.call(True, self.targets[
                    target_id].protocol_version)
            if self._info_cb:
                self._info_cb.call(self.targets[target_id])
            return True
        return False

    def request_info_update(self, target_id):
        print("Cloader: request_info_update:" + str(target_id))
        if target_id not in self.targets:
            self._update_info_nrf(target_id)
        if self._info_cb:
            self._info_cb.call(self.targets[target_id])
        print("Cloader: request_info_update:" + str(target_id)+'end')
        return self.targets[target_id]
    
    def request_info_update_nrf(self, target_id):
        print("Cloader: request_info_update:" + str(target_id))
        if target_id not in self.targets:
            self._update_info_nrf(target_id)
        if self._info_cb:
            self._info_cb.call(self.targets[target_id])
        print("Cloader: request_info_update:" + str(target_id)+'end')

    def _update_info_stm32(self, target_id):
        print("Cloader: _update_info start:"+str(target_id))
        """ Call the command getInfo and fill up the information received in
        the fields of the object
        """
        CMD_GET_INFO = 0x10
        CMD_GET_INFO_ACK = 0x20

        # Call getInfo ...
        pk = CRTPPacket()
        pk.set_header(0xFF, 0xFF)   # 设置port和channel
        pk.data = (target_id, CMD_GET_INFO)
        self.link.send_packet(pk)

        timeout = 10  # seconds
        ts = time.time()
        while time.time() - ts < timeout:
            # Wait for the answer
            answer = self.link.receive_packet(2)
            if answer is None:
                self.link.send_packet(pk)
            if (answer and answer.header == 0xFF and struct.unpack('<BB', answer.data[0:2]) ==
                    (target_id, CMD_GET_INFO_ACK)):
                tab = struct.unpack('BBHHHH', answer.data[0:10])
                # cpuid = struct.unpack('B' * 12, answer.data[10:22])
                cpuid = struct.unpack('>i', answer.data[10:14])  # 只有这一位是有效的
                # cpuid = struct.unpack('H', answer.data[10:12])

                if target_id not in self.targets:
                    self.targets[target_id] = Target(target_id)
                self.targets[target_id].addr = target_id
                if len(answer.data) > 22:
                    self.targets[target_id].protocol_version = answer.datat[22]
                    self.protocol_version = answer.datat[22]
                
                # if len(answer.data) > 12:
                #     self.targets[target_id].protocol_version = answer.datat[12]
                #     self.protocol_version = answer.datat[12]

                self.targets[target_id].page_size = tab[2]
                print("page size:"+str(tab[2]))
                self.targets[target_id].buffer_pages = tab[3]
                self.targets[target_id].flash_pages = tab[4]
                self.targets[target_id].start_page = tab[5]
                self.targets[target_id].cpuid = '%02X' % cpuid[0]
                for i in cpuid[1:]:
                    self.targets[target_id].cpuid += ':%02X' % i

                print("-- print cpu id start--")
                print('target id'+str(target_id))
                print(self.targets[target_id].cpuid)
                print("-- print cpu id end  --")
                if (self.protocol_version == 0x10 and
                        target_id == TargetTypes.STM32):
                    self._update_mapping(target_id)

                print("Cloader: _update_info true end")
                return True
        print("Cloader: _update_info false end") 
        return False
    
    
    def _update_info_stm32_alt(self, target_id):
        print("Cloader: _update_info alt start:"+str(target_id))
        """ Call the command getInfo and fill up the information received in
        the fields of the object
        """
        CMD_GET_INFO = 0x10
        CMD_GET_INFO_ACK = 0x20

        # Call getInfo ...
        pk = CRTPPacket()
        pk.set_header(0xFF, 0xFF)   # 设置port和channel
        pk.data = (target_id, CMD_GET_INFO)
        self.link.send_packet(pk)

        flag = False # 表示第几次接收到数据包
        timeout_times = 0 # 超时次数
        timeout_times_max = 3 # 超时次数最大值
        each_wait_time = 2  # 每次等待时间
        timeout = 10  # seconds
        ts = time.time()
        while time.time() - ts < timeout:
            # Wait for the answer
            answer = self.link.receive_packet(each_wait_time)
            if answer is None:
                timeout_times = timeout_times+1
                if timeout_times < timeout_times_max:
                    self.link.send_packet(pk)
                else:
                    if flag:
                        return True
                    else:
                        return False
            else:
                if (answer.header == 0xFF and struct.unpack('<BB', answer.data[0:2]) ==
                        (target_id, CMD_GET_INFO_ACK)):
                    tab = struct.unpack('BBHHHH', answer.data[0:10])
                    cpuid = struct.unpack('H', answer.data[10:12])
                    self.progress[cpuid]=0

                    if not flag:
                        flag = True
                        if target_id not in self.targets:
                            self.targets[target_id] = Target(target_id)
                        self.targets[target_id].addr = target_id
                        if len(answer.data) > 12:
                            self.targets[target_id].protocol_version = answer.datat[12]
                            self.protocol_version = answer.datat[12]

                        self.targets[target_id].page_size = tab[2]
                        print("page size:"+str(tab[2]))
                        self.targets[target_id].buffer_pages = tab[3]
                        self.targets[target_id].flash_pages = tab[4]
                        self.targets[target_id].start_page = tab[5]
                        self.targets[target_id].cpuid = '%02X' % cpuid[0]
                    else:
                        pass

                    print("-- print cpu id start--")
                    print('target id'+str(target_id))
                    print(self.targets[target_id].cpuid)
                    print("-- print cpu id end  --")
                    if (self.protocol_version == 0x10 and
                            target_id == TargetTypes.STM32):
                        self._update_mapping(target_id)

                    print("Cloader: _update_info true end")
                    return True
        print("Cloader: _update_info false end") 
        return False
    
    def _set_start_sencond_stage(self,target_id):
        CMD_START_SECOND_STAGE=0x31
        pk = CRTPPacket()
        pk.set_header(0xFF, 0xFF)   # 设置port和channel
        pk.data = (target_id, CMD_START_SECOND_STAGE)
        self.link.send_packet(pk)
        pass
    

    def _update_info_nrf(self, target_id=TargetTypes.NRF51):
        print("Cloader: _update_info_nrf start:"+str(target_id))
        """ Call the command getInfo and fill up the information received in
        the fields of the object
        """
        CMD_GET_INFO = 0x10
        CMD_GET_INFO_ACK = 0x20

        self.protocol_version = BootVersion.CF2_PROTO_VER
        return True
        # Call getInfo ...
        pk = CRTPPacket()
        pk.set_header(0xFF, 0xFF)   # 设置port和channel
        pk.data = (target_id, CMD_GET_INFO)
        self.link.send_packet(pk)

        timeout = 10  # seconds
        ts = time.time()
        while time.time() - ts < timeout:
            # Wait for the answer
            answer = self.link.receive_packet(2)
            if answer is None:
                self.link.send_packet(pk)

            if (answer and answer.header == 0xFF and struct.unpack('<BB', answer.data[0:2]) ==
                    (target_id, CMD_GET_INFO_ACK)):
                tab = struct.unpack('BBHHHH', answer.data[0:10])
                # cpuid = struct.unpack('B' * 12, answer.data[10:22])
                cpuid = struct.unpack('>i', answer.data[10:14])  # 只有这一位是有效的
                # cpuid = struct.unpack('H', answer.data[10:12])

                if target_id not in self.targets:
                    self.targets[target_id] = Target(target_id)
                self.targets[target_id].addr = target_id
                if len(answer.data) > 22:
                    self.targets[target_id].protocol_version = answer.datat[22]
                    self.protocol_version = answer.datat[22]
                
                # if len(answer.data) > 12:
                #     self.targets[target_id].protocol_version = answer.datat[12]
                #     self.protocol_version = answer.datat[12]

                # self.targets[target_id].page_size = tab[2]
                # self.targets[target_id].buffer_pages = tab[3]
                # self.targets[target_id].flash_pages = tab[4]
                # self.targets[target_id].start_page = tab[5]
                # self.targets[target_id].cpuid = '%02X' % cpuid[0]
                # for i in cpuid[1:]:
                #     self.targets[target_id].cpuid += ':%02X' % i

                print("-- print cpu id start--")
                print('target id'+str(target_id))
                print(self.targets[target_id].cpuid)
                print("-- print cpu id end  --")

                print("Cloader: _update_info true end")
                return True
        print("Cloader: _update_info false end") 
        return False

    def _update_mapping(self, target_id):
        return True
        print("Cloader: _update_mapping:"+str(target_id))
        pk = CRTPPacket()
        pk.set_header(0xff, 0xff)
        pk.data = (target_id, 0x12)
        self.link.send_packet(pk)

        pk = self.link.receive_packet(2)

        if (pk and pk.header == 0xFF and len(pk.data) >= 2 and struct.unpack('<BB', pk.data[0:2]) ==
                (target_id, 0x12)):
            m = pk.datat[2:]

            if (len(m) % 2) != 0:
                raise Exception('Malformed flash mapping packet')

            self.mapping = []
            page = 0
            for i in range(int(len(m) / 2)):
                for j in range(m[2 * i]):
                    self.mapping.append(page)
                    page += m[(2 * i) + 1]

    def upload_buffer(self, target_id, page, address, buff):
        # address是对页中的内容进行编号
        print("Cloader: upload_buffer "+str(target_id))
        """Upload data into a buffer on the Crazyflie"""
        # print len(buff)
        count = 0
        pk = CRTPPacket()
        pk.set_header(0xFF, 0xFF)
        pk.data = struct.pack('=BBHH', target_id, 0x14, page, address)

        for i in range(0, len(buff)):
            pk.data.append(buff[i])

            count += 1

            if count > 24:
                self.link.send_packet(pk)
                count = 0
                pk = CRTPPacket()
                pk.set_header(0xFF, 0xFF)
                pk.data = struct.pack('=BBHH', target_id, 0x14, page,
                                      i + address + 1)

        self.link.send_packet(pk)
    
    def upload_buffer_alt(self, target_id, page, address, buff):
        self.upload_buffer(target_id, page, address, buff)
        # while(self.upload_buffer_query_loss(target_id)):    # 只要还有未接收到的则重新loaderbuffer
        #     print("retry loader buffer page-"+str(page))
        #     self.upload_buffer(target_id, page, address, buff)


    def upload_buffer_query_loss(self,target_id):
        '''
        如果有丢失则返回true,没有丢失则返回false
        '''
        # 问一下谁有缺失
        CMD_QUERY_IS_LOSS=0x31
        CMD_QUERY_IS_LOSS_ACK=0x32
        pk = CRTPPacket()
        pk.set_header(0xFF, 0xFF)
        pk.data = struct.pack('=BB', target_id,CMD_QUERY_IS_LOSS)
        # 发送之前清空网络中遗留的数据包
        pk_left = self.link.receive_packet(0)
        while pk_left is not None:
                    pk_left = self.link.receive_packet(0)
        # 发送
        self.link.send_packet(pk)
        
        # 如果有丢失的，则会接收到数据包
        answer = self.link.receive_packet(0)
        while(answer): # answer不为空
            print("upload_buffer_query_loss 接收到数据包",end=",")
            if (answer.header == 0xFF and struct.unpack('<BB', answer.data[0:2]) ==
                        (target_id, CMD_QUERY_IS_LOSS_ACK)):
                print("确定已经丢包")
                # 清理掉其他的pk
                pk_left = self.link.receive_packet(0)
                while pk_left is not None:
                    pk_left = self.link.receive_packet(0)
                return True # 有丢失的返回True
            else:   # 虽然不为空，但是不是我想要的，则重新收集
                print("但是没有丢包")
                answer = self.link.receive_packet(2)
        return False
            
        
    def upload_buffer_all(self, target_id, page, address, buff):
        count = 0
        pk = CRTPPacket()
        pk.set_header(0xFF, 0xFF)
        pk.data = struct.pack('=BBHH', target_id, 0x14, page, address)

        for i in range(0, len(buff)):
            pk.data.append(buff[i])

            count += 1

            if count > 24:
                self.link.send_packet(pk)
                count = 0
                pk = CRTPPacket()
                pk.set_header(0xFF, 0xFF)
                pk.data = struct.pack('=BBHH', target_id, 0x14, page,
                                      i + address + 1)

        self.link.send_packet(pk)
        

    def read_flash(self, addr=0xFF, page=0x00):
        print("Cloader: read_flash")
        """Read back a flash page from the Crazyflie and return it"""
        buff = bytearray()

        page_size = self.targets[addr].page_size

        for i in range(0, int(math.ceil(page_size / 25.0))):
            pk = None
            retry_counter = 5
            while ((not pk or pk.header != 0xFF or
                    struct.unpack('<BB', pk.data[0:2]) != (addr, 0x1C)) and
                    retry_counter >= 0):
                pk = CRTPPacket()
                pk.set_header(0xFF, 0xFF)
                pk.data = struct.pack('<BBHH', addr, 0x1C, page, (i * 25))
                self.link.send_packet(pk)

                pk = self.link.receive_packet(1)
                retry_counter -= 1
            if (retry_counter < 0):
                return None
            else:
                buff += pk.data[6:]

        # For some reason we get one byte extra here...
        return buff[0:page_size]

    def write_flash(self, addr, page_buffer, target_page, page_count):
        print("Cloader: write_flash")

        """Initiate flashing of data in the buffer to flash."""
        # print "Write page", flashPage
        # print "Writing page [%d] and [%d] forward" % (flashPage, nPage)
        pk = None

        # Flushing downlink ...
        pk = self.link.receive_packet(0)
        while pk is not None:
            pk = self.link.receive_packet(0)

        CMD_WRITE_FLASH=0x18
        CMD_WRITE_FLASH_ACK = 0x28
        retry_counter = 5
        # print "Flasing to 0x{:X}".format(addr)
        while ((not pk or pk.header != 0xFF or len(pk.data) < 2 or
                struct.unpack('<BB', pk.data[0:2]) != (addr, CMD_WRITE_FLASH_ACK)) and
               retry_counter >= 0):
            pk = CRTPPacket()
            pk.set_header(0xFF, 0xFF)
            pk.data = struct.pack('<BBHHH', addr, CMD_WRITE_FLASH, page_buffer,
                                  target_page, page_count)
            self.link.send_packet(pk)

            # Timeout for writing to flash is raised from 1s (used elsewhere
            # in this module) to 2.5s because it may take more than a second
            # to erase a page on the STM32F405.
            #
            # See https://github.com/bitcraze/crazyflie-lib-python/issues/98
            # for more details.
            pk = self.link.receive_packet(2.5)
            retry_counter -= 1

        if retry_counter < 0:
            self.error_code = -1
            return False

        self.error_code = pk.data[3]

        return pk.data[2] == 1

    def decode_cpu_id(self, cpuid):
        print("Cloader: decode_cpu_id")
        
        """Decode the CPU id into a string"""
        ret = ()
        for i in cpuid.split(':'):
            ret += (eval('0x' + i),)

        return ret
