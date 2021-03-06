#!/usr/bin/python
#
# Copyright (c) 2014, Psiphon Inc.
# All rights reserved.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import os
import urllib2
import ssl
import subprocess
import time
import random
import copy
import shutil
from functools import wraps
try:
    import win32ui
    import win32con
    import _winreg
    REGISTRY_ROOT_KEY = _winreg.HKEY_CURRENT_USER
except ImportError as error:
    print error
    print 'NOTE: Running client tests will not be available.'

import psi_ops_build_windows


# Check usage restrictions here before using this service:
# http://www.whatismyip.com/faq/automation.asp

# Local service should be in same GeoIP region; local split tunnel will be in effect (not proxied)
# Remote service should be in different GeoIP region; remote split tunnel will be in effect (proxied)
CHECK_IP_ADDRESS_URL_LOCAL = 'http://automation.whatismyip.com/n09230945.asp'
CHECK_IP_ADDRESS_URL_REMOTE = 'http://automation.whatismyip.com/n09230945.asp'


def urlopen(url, timeout):
    if hasattr(ssl, 'SSLContext'):
        # Set up an SSL context for urllib2 to use which ignores invalid (and/or self-signed) SSL certificates
        nonValidatingSslContext = ssl.create_default_context()
        nonValidatingSslContext.check_hostname = False
        nonValidatingSslContext.verify_mode = ssl.CERT_NONE
        return urllib2.urlopen(url, timeout=timeout, context=nonValidatingSslContext).read()
    else:
        return urllib2.urlopen(url, timeout=timeout)


# if psi_build_config.py exists, load it and use psi_build_config.DATA_ROOT as the data root dir

if os.path.isfile('psi_data_config.py'):
    import psi_data_config
    CHECK_IP_ADDRESS_URL_LOCAL = psi_data_config.CHECK_IP_ADDRESS_URL_LOCAL
    CHECK_IP_ADDRESS_URL_REMOTE = psi_data_config.CHECK_IP_ADDRESS_URL_REMOTE


REGISTRY_PRODUCT_KEY = 'SOFTWARE\\Psiphon3'
REGISTRY_TRANSPORT_VALUE = 'Transport'
REGISTRY_SPLIT_TUNNEL_VALUE = 'SplitTunnel'

try:
    APPDATA_DIR = os.path.join(os.environ['APPDATA'], 'Psiphon3')
    APPDATA_BACKUP_DIR = os.path.join(os.environ['APPDATA'], 'Psiphon3.bak')
except:
    print "Could not set APPDATA_DIR and/or APPDATA_BACKUP_DIR, ignoring"


def retry_on_exception_decorator(function):
    @wraps(function)
    def wrapper(*args, **kwds):
        for i in range(4):
            try:
                if i > 0:
                    time.sleep(20)
                return function(*args, **kwds)
            except Exception as e:
                print str(e)
                pass
        raise e
    return wrapper


@retry_on_exception_decorator
def __test_web_server(ip_address, web_server_port, propagation_channel_id, web_server_secret):
    print 'Testing web server at %s...' % (ip_address,)
    get_request = 'https://%s:%s/handshake?propagation_channel_id=%s&sponsor_id=0&client_version=1&server_secret=%s&relay_protocol=SSH' % (
                    ip_address, web_server_port, propagation_channel_id, web_server_secret)
    # Reset the proxy settings (see comment below)
    urllib2.install_opener(urllib2.build_opener(urllib2.ProxyHandler()))
    
    response = urlopen(get_request, 10).read()
    return ('SSHPort: ' in response and
            'SSHUsername: ' in response and
            'SSHPassword: ' in response and
            'SSHHostKey: ' in response and
            'SSHObfuscatedPort: ' in response and
            'SSHObfuscatedKey: ' in response and
            'PSK: ' not in response)


@retry_on_exception_decorator
def __test_server(executable_path, transport, encoded_server_list, expected_egress_ip_addresses):
    # test:
    # - spawn client process, which starts the VPN
    # - sleep 5 seconds, which allows time to establish connection
    # - determine egress IP address and assert it matches host IP address
    # - post WM_CLOSE to gracefully shut down the client and its connection
    
    has_remote_check = len(CHECK_IP_ADDRESS_URL_REMOTE) > 0
    has_local_check = len(CHECK_IP_ADDRESS_URL_LOCAL) > 0
    
    servers_registry_value = 'Servers' + transport
    
    # Currently, tunnel-core will try to establish a connection on OSSH,SSH,MEEK
    # ports.  The SSH registry value is overlooked.  This forces the registry
    # value that is set SSH connections.
    if transport == 'SSH':
        servers_registry_value = 'ServersOSSH'

    # Internally we refer to "OSSH", but the display name is "SSH+", which is also used
    # in the registry setting to control which transport is used.
    if transport == 'OSSH':
        transport = 'SSH+'

    # Split tunnelling is not implemented for VPN.
    # Also, if there is no remote check, don't use split tunnel mode because we always want
    # to test at least one proxied case.

    if transport == 'VPN' or not has_remote_check:
        split_tunnel_mode = False
    else:
        split_tunnel_mode = random.choice([True, False])

    print 'Testing egress IP addresses %s in %s mode (split tunnel %s)...' % (
            ','.join(expected_egress_ip_addresses), transport, 'ENABLED' if split_tunnel_mode else 'DISABLED')

    try:
        proc = None
        transport_value, transport_type = None, None
        split_tunnel_value, split_tunnel_type = None, None
        servers_value, servers_type = None, None
        reg_key = _winreg.OpenKey(REGISTRY_ROOT_KEY, REGISTRY_PRODUCT_KEY, 0, _winreg.KEY_ALL_ACCESS)
        transport_value, transport_type = _winreg.QueryValueEx(reg_key, REGISTRY_TRANSPORT_VALUE)
        _winreg.SetValueEx(reg_key, REGISTRY_TRANSPORT_VALUE, None, _winreg.REG_SZ, transport)
        split_tunnel_value, split_tunnel_type = _winreg.QueryValueEx(reg_key, REGISTRY_SPLIT_TUNNEL_VALUE)
        # Enable split tunnel with registry setting
        _winreg.SetValueEx(reg_key, REGISTRY_SPLIT_TUNNEL_VALUE, None, _winreg.REG_DWORD, 1 if split_tunnel_mode else 0)
        servers_value, servers_type = _winreg.QueryValueEx(reg_key, servers_registry_value)
        _winreg.SetValueEx(reg_key, servers_registry_value, None, _winreg.REG_SZ, '\n'.join(encoded_server_list))
        # Move appdata to clear it
        if os.path.exists(APPDATA_BACKUP_DIR):
            shutil.rmtree(APPDATA_BACKUP_DIR)
        os.rename(APPDATA_DIR, APPDATA_BACKUP_DIR)

        proc = subprocess.Popen([executable_path])

        time.sleep(25)
        
        # In VPN mode, all traffic is routed through the proxy. In SSH mode, the
        # urlib2 ProxyHandler picks up the Windows Internet Settings and uses the
        # HTTP Proxy that is set by the client.
        urllib2.install_opener(urllib2.build_opener(urllib2.ProxyHandler()))

        if has_local_check:
            # Get egress IP from web site in same GeoIP region; local split tunnel is not proxied

            egress_ip_address = urlopen(CHECK_IP_ADDRESS_URL_LOCAL, 30).read().split('\n')[0]

            is_proxied = (egress_ip_address in expected_egress_ip_addresses)

            if (transport == 'VPN' or not split_tunnel_mode) and not is_proxied:
                raise Exception('Local case/VPN/not split tunnel: egress is %s and expected egresses are %s' % (
                                    egress_ip_address, ','.join(expected_egress_ip_addresses)))

            if transport != 'VPN' and split_tunnel_mode and is_proxied:
                raise Exception('Local case/not VPN/split tunnel: egress is %s and expected egresses are ANYTHING OTHER THAN %s' % (
                                    egress_ip_address, ','.join(expected_egress_ip_addresses)))

        if has_remote_check:
            # Get egress IP from web site in different GeoIP region; remote split tunnel is proxied

            egress_ip_address = urlopen(CHECK_IP_ADDRESS_URL_REMOTE, 30).read().split('\n')[0]

            is_proxied = (egress_ip_address in expected_egress_ip_addresses)

            if not is_proxied:
                raise Exception('Remote case: egress is %s and expected egresses are %s' % (
                                    egress_ip_address, ','.join(expected_egress_ip_addresses)))

    finally:
        if transport_type and transport_value:
            _winreg.SetValueEx(reg_key, REGISTRY_TRANSPORT_VALUE, None, transport_type, transport_value)
        if split_tunnel_value and split_tunnel_type:
            _winreg.SetValueEx(reg_key, REGISTRY_SPLIT_TUNNEL_VALUE, None, split_tunnel_type, split_tunnel_value)
        if servers_type and servers_value:
            _winreg.SetValueEx(reg_key, servers_registry_value, None, servers_type, servers_value)
        try:
            win32ui.FindWindow(None, psi_ops_build_windows.APPLICATION_TITLE).PostMessage(win32con.WM_CLOSE)
        except Exception as e:
            print e
        if proc:
            proc.wait()
        # Restore appdata
        if os.path.exists(APPDATA_BACKUP_DIR):
            if os.path.exists(APPDATA_DIR):
                shutil.rmtree(APPDATA_DIR)
            os.rename(APPDATA_BACKUP_DIR, APPDATA_DIR)


def test_server(ip_address, capabilities, web_server_port, web_server_secret, encoded_server_list,
                split_tunnel_url_format, split_tunnel_signature_public_key, split_tunnel_dns_server, version,
                expected_egress_ip_addresses, test_propagation_channel_id = '0', test_cases = None, executable_path = None):

    local_test_cases = copy.copy(test_cases) if test_cases else ['handshake', 'VPN', 'OSSH', 'SSH']

    for test_case in copy.copy(local_test_cases):
        if test_case == 'OSSH' and (capabilities['FRONTED-MEEK'] or capabilities['UNFRONTED-MEEK']):
            print 'Testing OSSH through meek'
            continue
        if (not capabilities[test_case]
            or (test_case == 'VPN' # VPN requires handshake, SSH or SSH+
                and not (capabilities['handshake'] or capabilities['OSSH'] or capabilities['SSH']))):
            print 'Server does not support %s' % (test_case,)
            local_test_cases.remove(test_case)

    results = {}

    for test_case in local_test_cases:

        print 'test case %s...' % (test_case,)

        if test_case == 'handshake':
            try:
                result = __test_web_server(ip_address, web_server_port, test_propagation_channel_id, web_server_secret)
                results['WEB'] = 'PASS' if result else 'FAIL'
            except Exception as ex:
                results['WEB'] = 'FAIL: ' + str(ex)
            #try:
            #    result = __test_web_server(ip_address, '443', test_propagation_channel_id, web_server_secret)
            #    results['443'] = 'PASS' if result else 'FAIL'
            #except Exception as ex:
            #    results['443'] = 'FAIL: ' + str(ex)
        elif test_case in ['VPN', 'OSSH', 'SSH']:
            if not executable_path:
                executable_path = psi_ops_build_windows.build_client(
                                    test_propagation_channel_id,
                                    '0',        # sponsor_id
                                    None,       # banner
                                    encoded_server_list,
                                    '',         # remote_server_list_signature_public_key
                                    ('','','','',''), # remote_server_list_url
                                    '',         # feedback_encryption_public_key
                                    '',         # feedback_upload_server
                                    '',         # feedback_upload_path
                                    '',         # feedback_upload_server_headers
                                    '',         # info_link_url
                                    '',         # upgrade_signature_public_key
                                    ('','','','',''), # upgrade_url
                                    '',         # get_new_version_url
                                    '',         # get_new_version_email
                                    '',         # faq_url
                                    '',         # privacy_policy_url
                                    split_tunnel_url_format,
                                    split_tunnel_signature_public_key,
                                    split_tunnel_dns_server,
                                    version,
                                    False,
                                    True)
            try:
                __test_server(executable_path, test_case, encoded_server_list, expected_egress_ip_addresses)
                results[test_case] = 'PASS'
            except Exception as ex:
                results[test_case] = 'FAIL: ' + str(ex)

    return results
