import base64
import datetime
import json
import logging
import urllib.parse

import OpenSSL.crypto as crypto
import aiohttp
import pytz
import requests

import esia_client.exceptions

logger = logging.getLogger(__name__)


class FoundLocation(esia_client.exceptions.EsiaError):
    def __init__(self, location: str, *args, **kwargs):
        super().__init__(*args, kwargs)
        self.location = location


def make_request(url: str, method: str = 'GET', **kwargs) -> dict:
    """
    Делает запрос по указанному URL с параметрами и возвращает словарь из JSON-ответа

    Keyword Args:
        headers: Request HTTP Headers
        params: URI HTTP request params
        data: POST HTTP data
        timeout: Timeout requests

    Raises:
        HttpError: Ошибка сети или вебсервера
        IncorrectJsonError: Ошибка парсинга JSON-ответа
    """
    try:
        response = requests.request(method, url, **kwargs)
        logger.debug(f'Status {response.status_code} from {method} request to {url} with {kwargs}')
        response.raise_for_status()
        if response.status_code in (200, 302) and response.headers.get('Location'):
            raise FoundLocation(location=response.headers.get('Location'))
        elif not response.headers['Content-type'].startswith('application/json'):
            logger.error(f'{response.headers["Content-type"]} -> {response.text}')
            raise esia_client.exceptions.IncorrectJsonError(
                f'Invalid content type -> {response.headers["content-type"]}'
            )
        return response.json()
    except requests.HTTPError as e:
        logger.error(e, exc_info=True)
        raise esia_client.exceptions.HttpError(e)
    except ValueError as e:
        logger.error(e, exc_info=True)
        raise esia_client.exceptions.IncorrectJsonError(e)


async def make_async_request(
        url: str, method: str = 'GET', **kwargs) -> dict:
    """
    Делает асинхронный запрос по указанному URL с параметрами и возвращает словарь из JSON-ответа

    Keyword Args:
        headers: Request HTTP Headers
        params: URI HTTP request params
        data: POST HTTP data
        timeout: Timeout requests

    Raises:
        HttpError: Ошибка сети или вебсервера
        IncorrectJsonError: Ошибка парсинга JSON-ответа
    """
    try:
        async with aiohttp.client.ClientSession() as session:
            async with session.request(method, url, **kwargs) as response:
                logger.debug(f'Status {response.status} from {method} request to {url} with {kwargs}')
                response.raise_for_status()
                if response.status in (200, 302) and response.headers.get('Location'):
                    raise FoundLocation(location=response.headers.get('Location'))
                elif not response.content_type.startswith('application/json'):
                    text = await response.text()
                    logger.error(f'{response.content_type} -> {text}')
                    raise esia_client.exceptions.IncorrectJsonError(
                        f'Invalid content type -> {response.content_type}'
                    )
                return await response.json()
    except aiohttp.client.ClientError as e:
        logger.error(e, exc_info=True)
        raise esia_client.exceptions.HttpError(e)
    except ValueError as e:
        logger.error(e, exc_info=True)
        raise esia_client.exceptions.IncorrectJsonError(e)


def sign(content: str, crt: crypto.X509, pkey: crypto.PKey) -> str:
    """
    Подписывает параметры запроса цифровой подписью

    Args:
        data: Данные, которые необходимо подписать
        crt: Путь до сертификата
        pkey: Путь до приватного ключа

    """
    bio_in = crypto._new_mem_buf(content.encode())
    PKCS7_DETACHED = 0x40
    pkcs7 = crypto._lib.PKCS7_sign(crt._x509, pkey._pkey, crypto._ffi.NULL, bio_in, PKCS7_DETACHED)
    bio_out = crypto._new_mem_buf()
    crypto._lib.i2d_PKCS7_bio(bio_out, pkcs7)
    sigbytes = crypto._bio_to_string(bio_out)
    return base64.urlsafe_b64encode(sigbytes).decode()


def get_timestamp() -> str:
    """
    Получение текущей временной метки
    """
    return datetime.datetime.now(pytz.utc).strftime('%Y.%m.%d %H:%M:%S %z').strip()


def decode_payload(base64string: str) -> dict:
    """
    Расшифровка информации из JWT токена

    Args:
        base64string: JSON в UrlencodedBaset64

    """
    offset = len(base64string) % 4
    base64string += '=' * (4 - offset) if offset else ''
    try:
        return json.loads(base64.urlsafe_b64decode(base64string))
    except (ValueError, Exception) as e:
        logger.error(e, exc_info=True)
        raise esia_client.exceptions.IncorrectMarkerError(e)


def format_uri_params(params: dict) -> str:
    """
    Форматирует строку с URI параметрами

    Args:
        params: параметры запроса

    """
    a = '&'.join((f'{key}={value}' for key, value in params.items()))

    return '&'.join((f'{key}={urllib.parse.quote(str(value).encode())}' for key, value in params.items()))
