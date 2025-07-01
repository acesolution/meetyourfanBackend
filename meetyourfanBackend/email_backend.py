import smtplib
import ssl
from django.core.mail.backends.smtp import EmailBackend

class CustomEmailBackend(EmailBackend):
    def open(self):
        if self.connection:
            return False
        connection_params = {
            'host': self.host,
            'port': self.port,
            'local_hostname': self.local_hostname,
            'timeout': self.timeout,
        }
        try:
            self.connection = smtplib.SMTP(**connection_params)
            self.connection.ehlo()
            if self.use_tls:
                # Create an SSL context that does not verify certificates
                context = ssl._create_unverified_context()
                self.connection.starttls(context=context)
                self.connection.ehlo()
            if self.username and self.password:
                self.connection.login(self.username, self.password)
            return True
        except Exception:
            if not self.fail_silently:
                raise
