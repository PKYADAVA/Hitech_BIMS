"""Pagination for the mobile API.

Two paginators, both emitting a ``_pagination`` block that the envelope lifts
into ``meta.pagination``:

* :class:`StandardPagination` — page-number, good enough for stable master
  lists (dropdown data).
* :class:`CursorPagination` — opaque-cursor, ordered by ``-created_at``; the
  correct choice for **infinite scroll over feeds/transactions** that get new
  rows inserted while the user scrolls (no duplicates/skips). Domain viewsets
  opt into this by setting ``pagination_class = CursorPagination``.
"""
from __future__ import annotations

from rest_framework.pagination import CursorPagination as _CursorPagination
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 200

    def get_paginated_response(self, data) -> Response:
        return Response(
            {
                "results": data,
                "_pagination": {
                    "type": "page",
                    "count": self.page.paginator.count,
                    "page": self.page.number,
                    "num_pages": self.page.paginator.num_pages,
                    "page_size": self.get_page_size(self.request),
                    "next": self.get_next_link(),
                    "previous": self.get_previous_link(),
                },
            }
        )


class CursorPagination(_CursorPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 200
    ordering = "-created_at"  # overridden per-view when the model lacks it

    def get_paginated_response(self, data) -> Response:
        # NB: DRF's CursorPagination sets self.page_size (not self.request) in
        # paginate_queryset, so read the applied size from there.
        return Response(
            {
                "results": data,
                "_pagination": {
                    "type": "cursor",
                    "page_size": self.page_size,
                    "next": self.get_next_link(),
                    "previous": self.get_previous_link(),
                },
            }
        )
