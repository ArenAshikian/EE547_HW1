# EE 547 HW1 Question 2

This folder contains Question 2.  
The main file is http_client.py.

The goal of this problem was to build a robust HTTP client that handles failures in a reasonable way instead of just retrying everything.

# Retry Strategy

The client only retries failures that are likely to be temporary.

Successful 2xx responses are never retried. If a response is slow, it is still treated as a success, but it is also logged as a slow response.

Client errors in the 4xx range are not retried. These usually mean the request itself is invalid or the resource does not exist, so retrying would not help.

Retries are only performed for server errors in the 5xx range, timeouts, and connection related errors, since these failures may succeed if the request is retried.

When a retryable failure happens, the client waits using exponential backoff with jitter before trying again. The delay increases with each retry and is capped at a maximum value. Once the maximum number of retries is reached, the client stops and reports a final failure.

# Testing

The client was tested using the provided URLProvider with a fixed random seed. All expected callbacks were triggered correctly and the provided validator passed with no failures.
