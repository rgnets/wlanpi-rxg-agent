import os
from typing import Optional

from cryptography import x509
from cryptography.hazmat.backends import default_backend

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.x509 import load_pem_x509_certificate, load_pem_x509_csr, CertificateSigningRequest, Certificate


class CertificateTool:

    def __init__(self, cert_directory: str, partner_id: Optional[str] = None):
        self.cert_directory = cert_directory

        if not partner_id:
            partner_id = "default"
        self.partner_id = partner_id
        self.key_file = os.path.join(self.cert_directory, f"{partner_id}-priv.key")
        self.csr_file = os.path.join(self.cert_directory, f"{partner_id}-csr.csr")
        self.ca_file = os.path.join(self.cert_directory, f"{partner_id}-ca.crt")
        self.cert_file = os.path.join(self.cert_directory, f"{partner_id}-cert.crt")

    @staticmethod
    def load_key(filename):
        with open(filename, "rb") as pem_in:
            pemlines = pem_in.read()
        private_key = load_pem_private_key(pemlines, None, default_backend())
        return private_key

    @staticmethod
    def save_key(pk, filename):
        pem = pk.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        with open(filename, "wb") as pem_out:
            pem_out.write(pem)
            os.chmod(filename, 0o600)

    def save_csr(self, csr: CertificateSigningRequest):
        pem = csr.public_bytes(
            encoding=serialization.Encoding.PEM,
        )
        with open(self.csr_file, "wb") as pem_out:
            pem_out.write(pem)

    def load_csr(self) -> CertificateSigningRequest:
        with open(self.csr_file, "rb") as pem_in:
            pem_lines = pem_in.read()
        data = load_pem_x509_csr(pem_lines, default_backend())
        return data

    def save_ca(self, ca: Certificate):
        return self.save_cert(ca, self.ca_file)

    def save_ca_from_pem(self, ca: str):
        self.save_cert_from_pem(cert=ca, cert_file=self.ca_file)

    def load_ca(self) -> Certificate:
        return self.load_cert(self.ca_file)

    def save_cert(self, cert: Certificate, cert_file: Optional[str] = None):
        if not cert_file:
            cert_file = self.cert_file
        pem = cert.public_bytes(
            encoding=serialization.Encoding.PEM,
        )
        with open(cert_file, "wb") as pem_out:
            pem_out.write(pem)

    def save_cert_from_pem(self, cert: str, cert_file: Optional[str] = None):
        # This seems a silly way to do it, but it will serve as a validator
        # so we don't store garbage.
        cert_data = load_pem_x509_certificate(cert.encode("utf-8"), default_backend())
        self.save_cert(cert=cert_data, cert_file=cert_file)

    def load_cert(self, cert_file: Optional[str] = None) -> Certificate:
        if not cert_file:
            cert_file = self.cert_file
        with open(cert_file, "rb") as pem_in:
            pem_lines = pem_in.read()
        data = load_pem_x509_certificate(pem_lines, default_backend())
        return data

    # Generate pkey
    def get_key(self, bits=4096):
        if os.path.exists(self.key_file):
            return self.load_key(self.key_file)
        else:
            private_key = rsa.generate_private_key(
                public_exponent=65537, key_size=bits, backend=default_backend()
            )
            self.save_key(private_key, self.key_file)
        return private_key

    # Generate Certificate Signing Request (CSR)
    def get_csr(self, node_name: str):

        if os.path.exists(self.csr_file):
            return self.load_csr()

        else:
            builder = x509.CertificateSigningRequestBuilder()
            builder = builder.subject_name(
                x509.Name(
                    [
                        x509.NameAttribute(x509.NameOID.COMMON_NAME, node_name),
                    ]
                )
            )
            builder = builder.add_extension(
                x509.BasicConstraints(ca=False, path_length=None),
                critical=True,
            )
            builder = builder.add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    crl_sign=True,
                    key_encipherment=True,
                    encipher_only=False,
                    decipher_only=False,
                    key_cert_sign=False,
                ),
                critical=True,
            )
            # builder = builder.add_attribute(
            #     AttributeOID.CHALLENGE_PASSWORD, b"changeit"
            # )
            request = builder.sign(self.get_key(), hashes.SHA256())
            self.save_csr(request)
            return request

    def get_csr_as_pem(self, node_name: str) -> str:
        csr = self.get_csr(node_name)
        return csr.public_bytes(
            encoding=serialization.Encoding.PEM,
        ).decode("utf-8")
