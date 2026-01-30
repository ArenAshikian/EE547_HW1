# EE 547 HW1 Question 1

This folder contains Question 1. The file name I used was merge_workers.py

Each worker runs independently and communicates using small messages written to files.



# Message Types

I used three message types.

# RANG
This is sent at the beginning so each worker knows the range of values the other worker has. If the worker has no data, it sends [], otherwise it sends [min, max, count]

This lets the workers quickly decide whether they can merge.


# HEAD
This is used when the ranges overlap and the workers need to coordinate. [] means the worker is empty or finished.  [x] means x is the current smallest value the worker has not output yet

Workers compare heads to decide who can output next.


# DONE
This means a worker is completely finished and is always sent as []


Once both workers send DONE, the merge is complete.


# Merge Strategy

The merge happens in two steps.

# Step 1: Range Check
Each worker sorts its own data and sends a RANG message.  
Once both ranges are known the worker picks one of three cases:

ME_FIRST
  All my values come before the partner's values, or the partner is empty.  
  I output everything and then send DONE.

PARTNER_FIRST
  All of the partner's values come before mine.  
  I wait for the partner to finish, then output everything.

Overlap 
  The ranges overlap, so neither worker can safely dump all values at once.
  This avoids unnecessary message passing when the data doesn't overlap.



# Step 2: Overlapping Ranges

When the workers’ value ranges overlap, they switch to HEAD mode. Each worker sends its current smallest (head) value to the other worker. A worker only outputs values when it is safe to do so, meaning its head value is less than, or allowed to proceed relative to, the partner’s head value. Output is produced in chunks of up to 10 values per step to ensure steady progress and fairness.

To prevent deadlock when both workers have the same head value, a fixed tie-breaking rule is used. Worker A is allowed to output when the head values are equal, while Worker B waits. This guarantees that progress is always made and the system cannot stall.

## Work Balancing

Work is naturally balanced based on the distribution of the data. When value ranges do not overlap, one worker performs most of the output, which avoids unnecessary coordination. When ranges do overlap, both workers actively participate by comparing head values and taking turns outputting results. Limiting the number of values output per step prevents any single worker from monopolizing the process.

This design keeps both workers busy when needed, minimizes coordination overhead, and ensures forward progress in all cases.


