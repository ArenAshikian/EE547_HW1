# EE 547 HW1 Question 3

This folder contains my solution for the durable event log problem. The main implementation is in event_logger.py, and testing was done using test.py with different seeds and parameters.

## Buffer Size Choice

I chose a buffer size of 30 packets. This is large enough to handle typical packet reordering from the message source, but small enough that crashes do not risk losing a large amount of buffered data.

## Flush Strategy

Packets are written to the log whenever the next expected sequence number is available, which allows contiguous packets to be written in order. The buffer is also flushed when it becomes full to avoid holding too much data in memory. On termination, the logger performs a best-effort flush of any remaining buffered packets.

## Gap Handling Approach

The logger tracks the next expected sequence number. If it does not appear after several received packets, a retransmit is requested. Retransmit requests are de-duplicated to avoid unnecessary repeats. If the gap persists and the buffer fills up, the logger skips the missing packet and continues writing to maintain coverage.

## Trade-offs Observed During Testing

During testing, this approach achieved high coverage, typically around 94 to 98 percent of packets logged. Ordering was mostly preserved, with only a small number of late writes in normal conditions. Under heavier loss or frequent crashes, more late entries appeared, but overall coverage remained high. The design prioritizes durability and reasonable ordering over perfect ordering.
