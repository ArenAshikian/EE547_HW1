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



# Step 2: Overlap Case
If the ranges overlap, workers switch to sending HEAD messages.

- Each worker sends its current smallest value
- A worker only outputs values when it is safe compared to the partner's head
- Values are output in chunks of up to 10 per step

To prevent deadlock when both heads are equal:
- Worker A outputs on equality
- Worker B waits

This guarantees that progress is always made.



# Work Balancing

Work is balanced naturally based on the data:

- In non-overlapping cases, only one worker does most of the output, which avoids extra coordination.
- In overlapping cases, both workers actively compare heads and take turns outputting values.
- Output is limited per step so no worker monopolizes the process.

This keeps both workers busy when needed and minimizes unnecessary work.


