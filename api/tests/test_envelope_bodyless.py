"""A 204 carries nothing, envelope included.

This is a wire-format rule rather than a matter of taste. RFC 9110 says a 204
response ends at its headers, so a client or proxy that believes the status
stops reading there. The envelope renderer wrapped one anyway, producing

    HTTP/1.1 204 No Content
    Content-Length: 51

    {"success": true, "data": null, "error": null, "meta": {}}

— a response that contradicts itself. Those 51 bytes stay in the keep-alive
connection and are read as the start of the next request on it, whose request
line is then ``{"success": true, ...``. nginx answers that with **505 HTTP
Version Not Supported**.

Which is exactly how it surfaced: on the deployed site the first DELETE from a
page worked, the second failed with 505, and reloading fixed it — because the
reload opened fresh connections. It never showed locally: the development
server is forgiving enough to hide it.

Every v1 DELETE was affected, the phone's included. Nothing had issued one
from the web app until the bird sale evidence card let a photograph be
removed.
"""
from __future__ import annotations

from rest_framework.response import Response

from django.test import SimpleTestCase

from api.envelope import EnvelopeJSONRenderer


def render(status_code, data=None):
    response = Response(data, status=status_code)
    return EnvelopeJSONRenderer().render(data, renderer_context={"response": response})


class EnvelopeBodylessTests(SimpleTestCase):
    def test_a_204_renders_nothing_at_all(self):
        self.assertEqual(render(204), b"")

    def test_a_304_renders_nothing_either(self):
        self.assertEqual(render(304), b"")

    def test_an_ordinary_success_still_gets_its_envelope(self):
        """The fix must not empty the responses that are supposed to speak."""
        body = render(200, {"id": 7})
        self.assertIn(b'"success": true', body.replace(b'"success":true',
                                                       b'"success": true'))
        self.assertIn(b'"id"', body)

    def test_a_201_still_gets_its_envelope(self):
        """A created photograph comes back in the body; the card reads its id
        from there to label the tile it draws."""
        self.assertIn(b'"id"', render(201, {"id": 9}))

    def test_a_refusal_still_carries_its_reason(self):
        body = render(400, {"image": ["Upload a valid image."]})
        self.assertIn(b"Upload a valid image.", body)
