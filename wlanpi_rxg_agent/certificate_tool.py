import os
from typing import Optional

import utils


class CertificateTool:

    def __init__(self, cert_directory: str, partner_id: Optional[str] = None):
        self.cert_directory = cert_directory

        if not partner_id:
            partner_id = "default"
        self.partner_id = partner_id
        # self.key_file = os.path.join(self.cert_directory, f"{partner_id}-priv.key")
        self.key_file = os.path.join(self.cert_directory, f"priv.key")
        # self.csr_file = os.path.join(self.cert_directory, f"{partner_id}-csr.csr")
        self.csr_file = os.path.join(self.cert_directory, f"csr.csr")
        self.ca_file = os.path.join(self.cert_directory, f"{partner_id}-ca.crt")
        self.cert_file = os.path.join(self.cert_directory, f"{partner_id}-cert.crt")

    @staticmethod
    def load_key(filename):
        with open(filename, "r") as pem_in:
            return pem_in.read()

    @staticmethod
    def save_key(pk: str, filename: str):
        with open(filename, "w") as pem_out:
            pem_out.write(pk)
            os.chmod(filename, 0o600)

    def save_csr(self, csr_string: str):
        with open(self.csr_file, "w") as pem_out:
            pem_out.write(csr_string)

    def load_csr(self) -> str:
        with open(self.csr_file, "r") as pem_in:
            return pem_in.read()

    def save_ca(self, ca: str):
        return self.save_cert(ca, self.ca_file)

    def load_ca(self) -> str:
        return self.load_cert(self.ca_file)

    def save_cert(self, cert: str, cert_file: Optional[str] = None):
        if not cert_file:
            cert_file = self.cert_file
        with open(cert_file, "w") as pem_out:
            pem_out.write(cert)

    def load_cert(self, cert_file: Optional[str] = None) -> str:
        if not cert_file:
            cert_file = self.cert_file
        with open(cert_file, "r") as pem_in:
            return pem_in.read()

    # Generate pkey
    def get_key(self, bits=4096) -> str:
        if os.path.exists(self.key_file):
            return self.load_key(self.key_file)
        else:
            new_key = CertificateTool.gen_key(bits=bits)
            self.save_key(new_key, self.key_file)
        return new_key

    @staticmethod
    def gen_key(bits=4096) -> str:
        return utils.run_command(["openssl", "genrsa", str(bits)]).output

    @staticmethod
    def gen_csr(cn: str, private_key: str) -> str:
        # return utils.run_command(["openssl", "req", "-new", "-noout", "-text", "-key", "client.key", "-subj", "\"/C=''/ST=''/L=''/O=''/CN=$commonName/emailAddress=''\""]).output
        return utils.run_command(
            [
                "openssl",
                "req",
                "-new",
                "-subj",
                f"/C=''/ST=''/L=''/O=''/CN={cn}/emailAddress=''",
                "-key",
                "/dev/stdin",
            ],
            input=private_key,
            shell=False,
        ).output

    # Generate Certificate Signing Request (CSR)
    def get_csr(self, node_name: str) -> str:
        if os.path.exists(self.csr_file):
            return self.load_csr()
        else:
            new_csr = CertificateTool.gen_csr(node_name, self.get_key())
            self.save_csr(new_csr)
            return new_csr


if __name__ == "__main__":
    key = CertificateTool.gen_key()
    print(key)
    csr = CertificateTool.gen_csr("testboy", key)
    print(csr)
