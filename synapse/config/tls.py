# -*- coding: utf-8 -*-
# Copyright 2014-2016 OpenMarket Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import os
from datetime import datetime
from hashlib import sha256

from unpaddedbase64 import encode_base64

from OpenSSL import crypto

from synapse.config._base import Config

logger = logging.getLogger()


class TlsConfig(Config):
    def read_config(self, config):

        acme_config = config.get("acme", {})
        self.acme_enabled = acme_config.get("enabled", False)
        self.acme_url = acme_config.get(
            "url", "https://acme-v01.api.letsencrypt.org/directory"
        )
        self.acme_port = acme_config.get("port", 8449)
        self.acme_bind_addresses = acme_config.get("bind_addresses", ["127.0.0.1"])
        self.acme_reprovision_threshold = acme_config.get("reprovision_threshold", 30)

        self.tls_certificate_file = os.path.abspath(config.get("tls_certificate_path"))
        self.tls_private_key_file = os.path.abspath(config.get("tls_private_key_path"))
        self._original_tls_fingerprints = config["tls_fingerprints"]
        self.tls_fingerprints = list(self._original_tls_fingerprints)
        self.no_tls = config.get("no_tls", False)

        # This config option applies to non-federation HTTP clients
        # (e.g. for talking to recaptcha, identity servers, and such)
        # It should never be used in production, and is intended for
        # use only when running tests.
        self.use_insecure_ssl_client_just_for_testing_do_not_use = config.get(
            "use_insecure_ssl_client_just_for_testing_do_not_use"
        )

        self.tls_certificate = None
        self.tls_private_key = None

    def is_disk_cert_valid(self, allow_self_signed=True):
        """
        Is the certificate we have on disk valid, and if so, for how long?

        Args:
            allow_self_signed (bool): Should we allow the certificate we
                read to be self signed?

        Returns:
            int: Days remaining of certificate validity.
            None: No certificate exists.
        """
        if not os.path.exists(self.tls_certificate_file):
            return None

        try:
            with open(self.tls_certificate_file, 'rb') as f:
                cert_pem = f.read()
        except Exception:
            logger.exception("Failed to read existing certificate off disk!")
            raise

        try:
            tls_certificate = crypto.load_certificate(crypto.FILETYPE_PEM, cert_pem)
        except Exception:
            logger.exception("Failed to parse existing certificate off disk!")
            raise

        if not allow_self_signed:
            if tls_certificate.get_subject() == tls_certificate.get_issuer():
                raise ValueError(
                    "TLS Certificate is self signed, and this is not permitted"
                )

        # YYYYMMDDhhmmssZ -- in UTC
        expires_on = datetime.strptime(
            tls_certificate.get_notAfter().decode('ascii'), "%Y%m%d%H%M%SZ"
        )
        now = datetime.utcnow()
        days_remaining = (expires_on - now).days
        return days_remaining

    def read_certificate_from_disk(self):
        """
        Read the certificates from disk.
        """
        self.tls_certificate = self.read_tls_certificate(self.tls_certificate_file)

        if not self.no_tls:
            self.tls_private_key = self.read_tls_private_key(self.tls_private_key_file)

        self.tls_fingerprints = list(self._original_tls_fingerprints)

        # Check that our own certificate is included in the list of fingerprints
        # and include it if it is not.
        x509_certificate_bytes = crypto.dump_certificate(
            crypto.FILETYPE_ASN1, self.tls_certificate
        )
        sha256_fingerprint = encode_base64(sha256(x509_certificate_bytes).digest())
        sha256_fingerprints = set(f["sha256"] for f in self.tls_fingerprints)
        if sha256_fingerprint not in sha256_fingerprints:
            self.tls_fingerprints.append({u"sha256": sha256_fingerprint})

    def default_config(self, config_dir_path, server_name, **kwargs):
        base_key_name = os.path.join(config_dir_path, server_name)

        tls_certificate_path = base_key_name + ".tls.crt"
        tls_private_key_path = base_key_name + ".tls.key"

        return (
            """\
        # PEM encoded X509 certificate for TLS.
        # You can replace the self-signed certificate that synapse
        # autogenerates on launch with your own SSL certificate + key pair
        # if you like.  Any required intermediary certificates can be
        # appended after the primary certificate in hierarchical order.
        tls_certificate_path: "%(tls_certificate_path)s"

        # PEM encoded private key for TLS
        tls_private_key_path: "%(tls_private_key_path)s"

        # Don't bind to the https port
        no_tls: False

        # List of allowed TLS fingerprints for this server to publish along
        # with the signing keys for this server. Other matrix servers that
        # make HTTPS requests to this server will check that the TLS
        # certificates returned by this server match one of the fingerprints.
        #
        # Synapse automatically adds the fingerprint of its own certificate
        # to the list. So if federation traffic is handled directly by synapse
        # then no modification to the list is required.
        #
        # If synapse is run behind a load balancer that handles the TLS then it
        # will be necessary to add the fingerprints of the certificates used by
        # the loadbalancers to this list if they are different to the one
        # synapse is using.
        #
        # Homeservers are permitted to cache the list of TLS fingerprints
        # returned in the key responses up to the "valid_until_ts" returned in
        # key. It may be necessary to publish the fingerprints of a new
        # certificate and wait until the "valid_until_ts" of the previous key
        # responses have passed before deploying it.
        #
        # You can calculate a fingerprint from a given TLS listener via:
        # openssl s_client -connect $host:$port < /dev/null 2> /dev/null |
        #   openssl x509 -outform DER | openssl sha256 -binary | base64 | tr -d '='
        # or by checking matrix.org/federationtester/api/report?server_name=$host
        #
        tls_fingerprints: []
        # tls_fingerprints: [{"sha256": "<base64_encoded_sha256_fingerprint>"}]

        ## Support for ACME certificate auto-provisioning.
        # acme:
        #    enabled: false
        ##   ACME path.
        ##   If you only want to test, use the staging url:
        ##   https://acme-staging.api.letsencrypt.org/directory
        #    url: 'https://acme-v01.api.letsencrypt.org/directory'
        ##   Port number (to listen for the HTTP-01 challenge).
        ##   Using port 80 requires utilising something like authbind, or proxying to it.
        #    port: 8449
        ##   Hosts to bind to.
        #    bind_addresses: ['127.0.0.1']
        ##   How many days remaining on a certificate before it is renewed.
        #    reprovision_threshold: 30
        """
            % locals()
        )

    def read_tls_certificate(self, cert_path):
        cert_pem = self.read_file(cert_path, "tls_certificate")
        return crypto.load_certificate(crypto.FILETYPE_PEM, cert_pem)

    def read_tls_private_key(self, private_key_path):
        private_key_pem = self.read_file(private_key_path, "tls_private_key")
        return crypto.load_privatekey(crypto.FILETYPE_PEM, private_key_pem)

    def generate_files(self, config):
        tls_certificate_path = config["tls_certificate_path"]
        tls_private_key_path = config["tls_private_key_path"]

        if not self.path_exists(tls_private_key_path):
            with open(tls_private_key_path, "wb") as private_key_file:
                tls_private_key = crypto.PKey()
                tls_private_key.generate_key(crypto.TYPE_RSA, 2048)
                private_key_pem = crypto.dump_privatekey(
                    crypto.FILETYPE_PEM, tls_private_key
                )
                private_key_file.write(private_key_pem)
        else:
            with open(tls_private_key_path) as private_key_file:
                private_key_pem = private_key_file.read()
                tls_private_key = crypto.load_privatekey(
                    crypto.FILETYPE_PEM, private_key_pem
                )

        if not self.path_exists(tls_certificate_path):
            with open(tls_certificate_path, "wb") as certificate_file:
                cert = crypto.X509()
                subject = cert.get_subject()
                subject.CN = config["server_name"]

                cert.set_serial_number(1000)
                cert.gmtime_adj_notBefore(0)
                cert.gmtime_adj_notAfter(10 * 365 * 24 * 60 * 60)
                cert.set_issuer(cert.get_subject())
                cert.set_pubkey(tls_private_key)

                cert.sign(tls_private_key, 'sha256')

                cert_pem = crypto.dump_certificate(crypto.FILETYPE_PEM, cert)

                certificate_file.write(cert_pem)
