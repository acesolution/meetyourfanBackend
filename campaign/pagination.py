# campaign/pagination.py
from rest_framework.pagination import PageNumberPagination

class SuggestedCampaignPagination(PageNumberPagination):
    # PageNumberPagination: DRF built-in paginator that reads ?page=1, ?page=2 ...
    page_size = 20

    # allow client to override per request: ?page_size=10
    page_size_query_param = "page_size"
    max_page_size = 50
