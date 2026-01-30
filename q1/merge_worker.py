import json
from pathlib import Path
from dataclasses import dataclass


@dataclass
class Message:
    msg_type: str   # Max 5 chars
    values: list[int]  # Max 10 integers


@dataclass
class WorkerStats:
    comparisons: int      # Number of comparison operations
    messages_sent: int    # Number of messages written
    messages_received: int # Number of messages read
    values_output: int    # Number of values written to output


class MergeWorker:
    def __init__(self,
                 worker_id: str,        # "A" or "B"
                 data: list[int],       # This worker's data (unsorted)
                 inbox: Path,           # Read messages from here
                 outbox: Path,          # Write messages here
                 output: Path,          # Append merged results here
                 state_file: Path):     # Persist state between steps
        self.worker_id = worker_id
        self.data = data
        self.inbox = inbox
        self.outbox = outbox
        self.output = output
        self.state_file = state_file
        self.stats = WorkerStats(0, 0, 0, 0)

        self.state: dict = self._load_state()

    def _load_state(self) -> dict:
        """Load state from file, or initialize if first run."""
        if self.state_file.exists():
            with open(self.state_file) as f:
                return json.load(f)
        return self._initial_state()

    def _save_state(self) -> None:
        """Persist state to file."""
        with open(self.state_file, "w") as f:
            json.dump(self.state, f)

    def _initial_state(self) -> dict:
        """Return initial state structure."""
        if len(self.data) > 0:
            my_min = min(self.data)
            my_max = max(self.data)
        else:
            my_min = None
            my_max = None

        my_count = len(self.data)

        return {
            "phase": "INIT",

            # Template fields
            "my_min": my_min,
            "my_max": my_max,
            "my_count": my_count,

            "partner_min": None,
            "partner_max": None,
            "partner_count": None,

            "data_index": 0,
            "output_count": 0,
            "sorted": False,

            "sent_my_range": False,
            "sent_initial_head": False,

            "partner_head": None,

            "done_sent": False,
            "partner_done": False,

            # The modes are None, ME_FIRST, and PARTNER_FIRST
            "mode": None,
        }

    def step(self) -> bool:
        outgoing = None

        # Sort once
        if self.state["sorted"] == False:
            self.data.sort()
            self.state["sorted"] = True

            self.state["my_count"] = len(self.data)

            if len(self.data) > 0:
                self.state["my_min"] = self.data[0]
                self.state["my_max"] = self.data[len(self.data) - 1]
            else:
                self.state["my_min"] = None
                self.state["my_max"] = None

        # Read one message if it exists
        msg = self._read_one_message()

        # Apply message
        if msg != None:
            t = msg["msg_type"]
            vals = msg["values"]

            if t == "RANG":
                if len(vals) == 0:
                    self.state["partner_min"] = None
                    self.state["partner_max"] = None
                    self.state["partner_count"] = 0
                else:
                    self.state["partner_min"] = vals[0]
                    self.state["partner_max"] = vals[1]
                    self.state["partner_count"] = vals[2]

            elif t == "HEAD":
                # HEAD [] means partner is empty or done
                if len(vals) == 0:
                    self.state["partner_head"] = None
                    if self.state["partner_count"] == None:
                        self.state["partner_count"] = 0
                else:
                    self.state["partner_head"] = vals[0]

            elif t == "DONE":
                self.state["partner_done"] = True
                self.state["partner_head"] = None
                if self.state["partner_count"] == None:
                    self.state["partner_count"] = 0

        phase = self.state["phase"]

        # Initialization phase
        if phase == "INIT":
            # send my range once
            if self.state["sent_my_range"] == False:
                self.state["sent_my_range"] = True

                if self.state["my_count"] == 0:
                    outgoing = {"msg_type": "RANG", "values": []}
                else:
                    outgoing = {"msg_type": "RANG", "values": []}
                    outgoing["values"].append(self.state["my_min"])
                    outgoing["values"].append(self.state["my_max"])
                    outgoing["values"].append(self.state["my_count"])

            # after I know partner range decide a merge mode
            if self.state["sent_my_range"] == True:
                if self.state["partner_count"] != None:
                    pmn = self.state["partner_min"]
                    pmx = self.state["partner_max"]
                    pcount = self.state["partner_count"]

                    # If I am empty
                    if self.state["my_count"] == 0:
                        self.state["mode"] = None

                    # If partner is empty 
                    elif pcount == 0:
                        self.state["mode"] = "ME_FIRST"

                    else:
                        # If my max is  less than partner min
                        if self.state["my_max"] != None and pmn != None and self.state["my_max"] < pmn:
                            self.state["mode"] = "ME_FIRST"

                        # If partner max is  less than my min
                        elif pmx != None and self.state["my_min"] != None and pmx < self.state["my_min"]:
                            self.state["mode"] = "PARTNER_FIRST"

                        else:
                            # ranges overlap
                            self.state["mode"] = None

                    self.state["phase"] = "MERG"

        # Merge phase
        elif phase == "MERG":
            my_cur = self._my_cur()

            # If I come before partner
            if self.state["mode"] == "ME_FIRST":
                if my_cur != None:
                    out_vals = []
                    while len(out_vals) < 10:
                        my_cur = self._my_cur()
                        if my_cur == None:
                            break
                        out_vals.append(my_cur)
                        self.state["data_index"] = self.state["data_index"] + 1
                    self._append_output(out_vals)
                else:
                    if self.state["done_sent"] == False:
                        self.state["done_sent"] = True
                        outgoing = {"msg_type": "DONE", "values": []}

                if self.state["done_sent"] == True:
                    if self.state["partner_done"] == True:
                        self.state["phase"] = "DONE"

            # If partner comes first
            elif self.state["mode"] == "PARTNER_FIRST":
                if self.state["partner_done"] == True:
                    if my_cur != None:
                        out_vals = []
                        while len(out_vals) < 10:
                            my_cur = self._my_cur()
                            if my_cur == None:
                                break
                            out_vals.append(my_cur)
                            self.state["data_index"] = self.state["data_index"] + 1
                        self._append_output(out_vals)
                    else:
                        if self.state["done_sent"] == False:
                            self.state["done_sent"] = True
                            outgoing = {"msg_type": "DONE", "values": []}

                    if self.state["done_sent"] == True:
                        if self.state["partner_done"] == True:
                            self.state["phase"] = "DONE"

            # HEAD exchange
            else:
                # Send first HEAD
                if self.state["sent_initial_head"] == False:
                    self.state["sent_initial_head"] = True

                    if my_cur == None:
                        self.state["done_sent"] = True
                        outgoing = {"msg_type": "DONE", "values": []}
                    else:
                        outgoing = {"msg_type": "HEAD", "values": [my_cur]}

                else:
                    # If empty send DONE
                    if my_cur == None:
                        if self.state["done_sent"] == False:
                            self.state["done_sent"] = True
                            outgoing = {"msg_type": "DONE", "values": []}

                        if self.state["done_sent"] == True:
                            if self.state["partner_done"] == True:
                                self.state["phase"] = "DONE"

                    else:
                        # Only do work if I know partner head
                        if self._partner_head_known() == True:
                            if self._partner_empty() == True:
                                out_vals = []
                                while len(out_vals) < 10:
                                    my_cur = self._my_cur()
                                    if my_cur == None:
                                        break
                                    out_vals.append(my_cur)
                                    self.state["data_index"] = self.state["data_index"] + 1

                                self._append_output(out_vals)

                                nxt = self._my_cur()
                                if nxt == None:
                                    if self.state["done_sent"] == False:
                                        self.state["done_sent"] = True
                                        outgoing = {"msg_type": "DONE", "values": []}
                                else:
                                    outgoing = {"msg_type": "HEAD", "values": [nxt]}

                            else:
                                ph = self.state["partner_head"]
                                out_vals = []

                                while len(out_vals) < 10:
                                    my_cur = self._my_cur()
                                    if my_cur == None:
                                        break

                                    self.stats.comparisons = self.stats.comparisons + 1

                                    if my_cur < ph:
                                        out_vals.append(my_cur)
                                        self.state["data_index"] = self.state["data_index"] + 1

                                    else:
                                        if my_cur == ph:
                                            if self.worker_id == "A":
                                                out_vals.append(my_cur)
                                                self.state["data_index"] = self.state["data_index"] + 1
                                            else:
                                                break
                                        else:
                                            break

                                if len(out_vals) > 0:
                                    self._append_output(out_vals)

                                    nxt = self._my_cur()
                                    if nxt == None:
                                        if self.state["done_sent"] == False:
                                            self.state["done_sent"] = True
                                            outgoing = {"msg_type": "DONE", "values": []}
                                    else:
                                        outgoing = {"msg_type": "HEAD", "values": [nxt]}

                        if self.state["done_sent"] == True:
                            if self.state["partner_done"] == True:
                                self.state["phase"] = "DONE"

        # Done phase
        elif phase == "DONE":
            if self.state["done_sent"] == False:
                self.state["done_sent"] = True
                outgoing = {"msg_type": "DONE", "values": []}

            if self.state["partner_done"] == True:
                self._save_state()
                return False

        # Write one message
        if outgoing != None:
            self._write_message(outgoing)

        # Save state
        self._save_state()

        # Return if there is still work
        if self.state["phase"] == "DONE":
            return False
        return True

    def get_stats(self) -> WorkerStats:
        """Return statistics about work performed."""
        return self.stats

    # Some helper functions so that I don't have to repeat logic
    def _read_one_message(self):
        if self.inbox.exists() == False:
            return None

        try:
            if self.inbox.stat().st_size <= 0:
                return None

            raw = self.inbox.read_text(encoding="utf-8").strip()
            if raw == "":
                return None

            obj = json.loads(raw)

            # clear inbox so it behaves like a dropbox
            self.inbox.write_text("", encoding="utf-8")

            self.stats.messages_received = self.stats.messages_received + 1

            mt = obj.get("msg_type", "")
            vals = obj.get("values", [])

            if mt == None:
                mt = ""
            if vals == None:
                vals = []

            # enforce constraints just in case
            mt = mt[:5]
            vals = vals[:10]

            return {"msg_type": mt, "values": vals}

        except Exception:
            return None

    def _write_message(self, outgoing):
        payload = {
            "msg_type": outgoing["msg_type"][:5],
            "values": outgoing["values"][:10],
        }
        self.outbox.write_text(json.dumps(payload), encoding="utf-8")
        self.stats.messages_sent = self.stats.messages_sent + 1

    def _append_output(self, vals: list[int]) -> None:
        if vals == None:
            return
        if len(vals) == 0:
            return

        with open(self.output, "a", encoding="utf-8") as f:
            for v in vals:
                f.write(str(v) + "\n")

        self.stats.values_output = self.stats.values_output + len(vals)
        self.state["output_count"] = self.state["output_count"] + len(vals)

    def _my_cur(self):
        i = self.state["data_index"]
        if i >= len(self.data):
            return None
        return self.data[i]

    def _partner_empty(self) -> bool:
        if self.state["partner_done"] == True:
            return True
        if self.state["partner_count"] == 0:
            return True
        return False

    def _partner_head_known(self) -> bool:
        if self._partner_empty() == True:
            return True
        if self.state["partner_head"] != None:
            return True
        return False
