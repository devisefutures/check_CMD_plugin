#!/usr/bin/env python3
###############################################################################
# Verifica se o SCMD está a responder, podendo ser utilizado no nagios ou icinga.
#
# chdck_scmd.py  (Python 3)
#
# Copyright (c) 2019 Devise Futures, Lda.
# Developed by José Miranda - jose.miranda@devisefutures.com
#
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
#
###############################################################################
"""
Programa (em Python3) cujo objetivo é verificar se o serviço SCMD está a responder, para o que
utiliza a operação GetCertificate (conforme versão 1.6 da especificação CMD):
  + GetCertificate
          (applicationId: xsd:base64Binary, userId: xsd:string)
          -> GetCertificateResult: xsd:string

Verifica o serviço SCMD em preprod e prod, cujo WSDL se encontra respetivamente em
https://preprod.cmd.autenticacao.gov.pt/Ama.Authentication.Frontend/CCMovelDigitalSignature.svc?wsdl
e https://cmd.autenticacao.gov.pt/Ama.Authentication.Frontend/CCMovelDigitalSignature.svc?wsdl
"""

import sys
import argparse           # parsing de argumentos comando linha
import signal
import logging.config     # debug
from functools import partial
import pem
import time
from OpenSSL import crypto
from zeep import Client   # zeep para SOAP
from zeep.transports import Transport


TEXT = 'check_scmd Command Line Program (for Preprod/Prod Signature CMD (SOAP) version 1.6 technical specification)'
__version__ = '1.0'


# Função que devolve o URL do WSDL do SCMD (preprod ou prod)
def get_wsdl(env):
    """Devolve URL do WSDL do SCMD.

    Parameters
    ----------
    t : int
        WSDL a devolver: 0 para preprod, 1 para prod.

    Returns
    -------
    string
        URL do WSDL do SCMD.

    """
    wsdl = {
        0: 'https://preprod.cmd.autenticacao.gov.pt/Ama.Authentication.Frontend/CCMovelDigitalSignature.svc?wsdl',
        1: 'https://cmd.autenticacao.gov.pt/Ama.Authentication.Frontend/CCMovelDigitalSignature.svc?wsdl'
    }
    # Get the function from switcher dictionary
    return wsdl.get(env, lambda: 'No valid WSDL')


# Função que devolve o cliente de ligação (preprod ou prod) ao servidor SOAP da CMD
def getclient(env=0, timeout=10):
    """Devolve o cliente de ligação ao servidor SOAP da CMD.

    Parameters
    ----------
    env: int
        WSDL a devolver: 0 para preprod, 1 para prod.
    timeout: int
        Valor máximo que espera para estabelever ligação com o servidor SOAP da CMD

    Returns
    -------
    Zeep.Client
        Devolve o cliente de ligação ao servidor SOAP da CMD. Por defeito devolve o
        servidor de preprod.

    """
    transport = Transport(timeout=timeout)
    return Client(get_wsdl(env), transport=transport)


# GetCertificate(applicationId: xsd:base64Binary, userId: xsd:string)
#                                       -> GetCertificateResult: xsd:string
def getcertificate(client, args):
    """Prepara e executa o comando SCMD GetCertificate.

    Parameters
    ----------
    client : Client (zeep)
        Client inicializado com o WSDL.
    args : argparse.Namespace
        argumentos a serem utilizados na mensagem SOAP.

    Returns
    -------
    str
        Devolve o certificado do cidadão e a hierarquia de certificação.

    """
    request_data = {
        'applicationId': args.a.encode('UTF-8'),
        'userId': args.user
    }
    return client.service.GetCertificate(**request_data)


# Função para ativar o debug, permitindo mostrar mensagens enviadas e recebidas do servidor SOAP
def debug():
    """Activa o debug, mostrando as mensagens enviadas e recebidas do servidor SOAP."""
    logging.config.dictConfig({
        'version': 1,
        'formatters': {
            'verbose': {'format': '>> %(name)s: %(message)s'}
        },
        'handlers': {
            'console': {
                'level': 'DEBUG',
                'class': 'logging.StreamHandler',
                'formatter': 'verbose',
            },
        },
        'loggers': {
            'zeep.transports': {
                'level': 'DEBUG',
                'propagate': True,
                'handlers': ['console'],
            },
        }
    })


def handle_sigalrm(signum, frame, timeout=None):
    output('Plugin timed out after %d seconds' % timeout, 3)


def output(label, state=0, lines=None, perfdata=None, name='scmd'):
    if lines is None:
        lines = []
    if perfdata is None:
        perfdata = {}

    pluginoutput = ""

    if state == 0:
        pluginoutput += "OK"
    elif state == 1:
        pluginoutput += "WARNING"
    elif state == 2:
        pluginoutput += "CRITICAL"
    elif state == 3:
        pluginoutput += "UNKNOWN"
    else:
        raise RuntimeError("ERROR: State programming error.")

    pluginoutput += " - "

    pluginoutput += name + ': ' + str(label)

    if len(lines):
        pluginoutput += ' - '
        pluginoutput += ' '.join(lines)

    if perfdata:
        pluginoutput += '|'
        pluginoutput += ' '.join(["'" + key + "'" + '=' + str(value)
                                  for key, value in perfdata.items()])

    print(pluginoutput)
    sys.exit(state)


def main():
    """Função main do programa."""
    init = time.time()
    args = args_parse()
    # O signal só vai ocorrer após 5 segundos do timeout de ligação ao serviço SCMD, caso o
    # programa ainda não tenha terminado (altamente improvável)
    signal.signal(signal.SIGALRM, partial(
        handle_sigalrm, timeout=args.timeout+5))
    signal.alarm(args.timeout+5)
    if args.verbose:
        debug()
    client = getclient(args.prod, args.timeout)
    check(args.func(client, args), init, args.warning, args.critical)


def args_parse():
    """Define as várias opções do comando linha."""
    parser = argparse.ArgumentParser()
    parser.add_argument('-V', '--version', help='show program version', action='version',
                        version='%(prog)s v' + sys.modules[__name__].__version__)
    parser.add_argument('-v', '--verbose',
                        help='show debug information', action='store_true')
    parser.add_argument('-u', '--user', action='store', help='user phone number (+XXX NNNNNNNNN)',
                        required=True)
    parser.add_argument('-a', '-applicationId', action='store',
                        help='CMD ApplicationId', required=True)
    parser.add_argument('-prod', action='store_true',
                        help='Use production SCMD service (preproduction SCMD service used by default)')
    parser.add_argument("-w", "--warning", type=int, default=3,
                        help="Warning threshold (time to service response) in seconds (default 3s).")
    parser.add_argument("-c", "--critical", type=int, default=6,
                        help="Critical threshold (time to service response) in seconds (default 6s).")
    parser.add_argument("-t", "--timeout", help="Timeout in seconds (default 25s)", type=int,
                        default=20)
    parser.set_defaults(func=getcertificate)

    return parser.parse_args()


# Verifica o resultado e termina o programa
def check(result, init_time, warning, critical):
    """Verifica o resultado e termina o programa, no caso normal em que não existe timeout.

    Parameters
    ----------
    result : string
        hierarquia de certificados em formato PEM.
    init_time: time
        tempo a que se iniciou a execução do programa
    warning: int
        tempo limite de execução do programa, para ser considerado warning
    critical: int
        tempo limite de execução do programa, para ser considerado critical

    """
    if result is None:
        output('Impossível obter certificado', 2)
        exit()
    # certs[0] = user; certs[1] = root; certs[2] = CA
    certs = pem.parse(result.encode())
    certs_chain = {'user': crypto.load_certificate(crypto.FILETYPE_PEM, certs[0].as_bytes()),
                   'ca': crypto.load_certificate(crypto.FILETYPE_PEM, certs[2].as_bytes()),
                   'root': crypto.load_certificate(crypto.FILETYPE_PEM, certs[1].as_bytes())
                   }
    status = 0
    time_seconds = round(time.time() - init_time, 5)
    if time_seconds > critical:
        status = 2
    elif time_seconds > warning:
        status = 1
    output('Certificado emitido para "' + certs_chain['user'].get_subject().CN +
           '" pela Entidade de Certificação "' + certs_chain['ca'].get_subject().CN +
           '" na hierarquia do "' +
           certs_chain['root'].get_subject().CN + '"', status, [],
           {"time_seconds": time_seconds})


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        pass
    except:  # catch *all* exceptions
        e = sys.exc_info()
        output("Error: %s" % str(e), 2)
