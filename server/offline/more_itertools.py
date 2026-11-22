"""The two more_itertools helpers endplay uses, so the browser bundle needs no extra package."""
from itertools import islice, zip_longest


def chunked(iterable, n):
    it = iter(iterable)
    while chunk := list(islice(it, n)):
        yield chunk


def grouper(iterable, n, incomplete="fill", fillvalue=None):
    return zip_longest(*[iter(iterable)] * n, fillvalue=fillvalue)
