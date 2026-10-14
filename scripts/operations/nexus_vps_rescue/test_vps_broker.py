"""Validate key isolation and actual OpenSSH configuration interpretation."""
import base64
import copy
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

if __package__:
    from . import vps_broker as broker
else:
    import vps_broker as broker


def key(byte: int, node: str) -> str:
    blob = struct.pack('>I', 11) + b'ssh-ed25519' + struct.pack('>I', 32) + bytes([byte]) * 32
    return 'ssh-ed25519 ' + base64.b64encode(blob).decode() + ' NEXUS-RESCUE-' + node


def exports() -> list[dict]:
    return [dict(schema='nexus-rescue-forward-key-v1', node=node, hostname=host, user='afaq', forward_public_key=key(i + 1, node), private_key_exported=False, writer_authority=False, live_enabled=False) for i, (node, (host, port)) in enumerate(broker.NODES.items())]


class BrokerTests(unittest.TestCase):
    def test_good_exports_and_one_port_per_key(self):
        values = broker.validate_exports(exports())
        lines = broker.render_authorized_keys(values).decode().splitlines()
        self.assertEqual(len(lines), 2)
        for node, line in zip(broker.NODES, lines):
            self.assertIn('restrict,port-forwarding,permitlisten="127.0.0.1:' + str(broker.NODES[node][1]) + '"', line)
            self.assertNotIn('0.0.0.0', line)
            self.assertNotIn('command=', line)

    def test_bad_identity_and_authority_rejected(self):
        for field, value in [('schema','other'),('hostname','OTHER'),('node','OTHER'),('user','root'),('private_key_exported',True),('writer_authority',True),('live_enabled',True)]:
            with self.subTest(field=field):
                data = exports(); data[0][field] = value
                with self.assertRaises(ValueError): broker.validate_exports(data)

    def test_missing_null_or_duplicate_nodes_rejected(self):
        for data in [None, [], exports()[:1], exports() + exports()[:1], [exports()[0]] * 2]:
            with self.subTest(data=data):
                with self.assertRaises(ValueError): broker.validate_exports(data)

    def test_same_identity_on_both_nodes_rejected(self):
        data = exports(); data[1]['forward_public_key'] = key(1, 'LAPTOP2')
        with self.assertRaises(ValueError): broker.validate_exports(data)

    def test_key_option_newline_and_blob_injection_rejected(self):
        for value in [key(1,'LAPTOP1')+'\nssh-rsa bad', 'command="sh" '+key(1,'LAPTOP1'), 'ssh-ed25519 AAAA NEXUS-RESCUE-LAPTOP1', key(1,'LAPTOP2')]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError): broker.validate_public_key(value,'NEXUS-RESCUE-LAPTOP1')

    def test_real_sshd_match_blocks_sessions_and_preserves_root(self):
        if not Path('/usr/sbin/sshd').exists(): self.skipTest('OpenSSH Server unavailable')
        if os.name == 'posix' and not Path('/run/sshd').exists() and os.uname().sysname == 'Linux': self.skipTest('OpenSSH privilege separation directory absent; provisioner does not mutate CI host')
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp); hostkey=folder/'host'
            subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(hostkey)],check=True)
            base=(f'HostKey {hostkey}\nPasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\nAllowTcpForwarding yes\nGatewayPorts no\nPidFile {folder}/pid\n').encode()
            original=folder/'old'; candidate=folder/'new'
            original.write_bytes(base); candidate.write_bytes(base+broker.render_block())
            subprocess.run(['/usr/sbin/sshd','-t','-f',str(candidate)],check=True,capture_output=True)
            self.assertEqual(broker.effective(original,'root'),broker.effective(candidate,'root'))
            config=broker.effective(candidate,'nexusrescue')
            for name,value in {'maxsessions':'0','gatewayports':'no','permitlisten':'127.0.0.1:2201 127.0.0.1:2202','permitopen':'none','allowtcpforwarding':'remote','allowstreamlocalforwarding':'no','passwordauthentication':'no','kbdinteractiveauthentication':'no','allowagentforwarding':'no','permittty':'no'}.items():
                self.assertEqual(config.get(name),value,name)

    def test_apply_refuses_wrong_host_before_mutation(self):
        if not hasattr(os,'geteuid'): self.skipTest('VPS provisioner is Linux only')
        if broker.socket.gethostname() == 'vm39793-59152.mobinhost.com': self.skipTest('Do not run wrong-host test on VPS')
        with self.assertRaisesRegex(RuntimeError,'authenticated'): broker.apply(broker.validate_exports(exports()))

    def test_atomic_public_file_mode_and_symlink_rejection(self):
        if not hasattr(os,'fchmod'): self.skipTest('POSIX file-mode validation')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'keys'
            previous=os.umask(0o077)
            try: broker.atomic_write(path,b'public\n',0o644)
            finally: os.umask(previous)
            self.assertEqual(path.stat().st_mode & 0o777,0o644)
            link=Path(tmp)/'link'; link.symlink_to(path)
            with self.assertRaisesRegex(RuntimeError,'symlink'): broker.atomic_write(link,b'changed\n')
            self.assertEqual(path.read_bytes(),b'public\n')


if __name__ == '__main__':
    unittest.main()
