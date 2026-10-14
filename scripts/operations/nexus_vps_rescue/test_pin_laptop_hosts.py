import base64
import copy
import hashlib
import unittest
if __package__:
    from . import pin_laptop_hosts as pin
    from . import test_vps_broker as fixtures
    from . import vps_broker as broker
else:
    import pin_laptop_hosts as pin
    import test_vps_broker as fixtures
    import vps_broker as broker


def installed():
    result=[]
    for i, forward in enumerate(fixtures.exports()):
        host=fixtures.key(i+3,forward['node']).replace('NEXUS-RESCUE-','NEXUS-RESCUE-HOST-')
        blob=base64.b64decode(host.split()[1])
        fingerprint='SHA256:'+base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('=')
        result.append(dict(schema='nexus-rescue-install-v1',node=forward['node'],hostname=forward['hostname'],port=broker.NODES[forward['node']][1],status='INSTALLED_PENDING_VPS_SSH_ACCEPTANCE',writer_authority=False,live_enabled=False,forward_public_key=forward['forward_public_key'],host_public_key=host,host_fingerprint='256 '+fingerprint+' comment (ED25519)'))
    return result


class PinTests(unittest.TestCase):
    def setUp(self):
        self.auth=broker.render_authorized_keys(broker.validate_exports(fixtures.exports())).decode()

    def test_verified_keys_pin_exact_loopback_ports(self):
        lines=pin.validated_lines(installed(),self.auth).splitlines()
        self.assertEqual([line.split()[0] for line in lines],['[127.0.0.1]:2201','[127.0.0.1]:2202'])
        self.assertTrue(all(line.split()[1]=='ssh-ed25519' for line in lines))

    def test_wrong_fingerprint_or_unregistered_forwarding_identity_rejected(self):
        for field,value in [('host_fingerprint','256 SHA256:wrong'),('forward_public_key',fixtures.key(12,'LAPTOP1'))]:
            with self.subTest(field=field):
                data=installed();data[0][field]=value
                with self.assertRaises(ValueError):pin.validated_lines(data,self.auth)

    def test_incomplete_status_authority_and_node_changes_rejected(self):
        for field,value in [('status','FAILED'),('port',2202),('hostname','OTHER'),('writer_authority',True),('live_enabled',True)]:
            with self.subTest(field=field):
                data=installed();data[0][field]=value
                with self.assertRaises(ValueError):pin.validated_lines(data,self.auth)

    def test_missing_duplicate_or_shared_host_identity_rejected(self):
        data=installed();data[1]['host_public_key']=data[0]['host_public_key'].replace('HOST-LAPTOP1','HOST-LAPTOP2');data[1]['host_fingerprint']=data[0]['host_fingerprint']
        for value in [[],installed()[:1],[installed()[0]]*2,data]:
            with self.assertRaises(ValueError):pin.validated_lines(value,self.auth)


if __name__=='__main__':unittest.main()
