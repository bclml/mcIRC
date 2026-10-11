"""Fun bot: jokes, dad jokes and facts from free online collections (no keys) - thousands instead of the few dozen built in - and
never the same one twice in a row: what was told lately is remembered (also over restarts) and skipped.  Offline, or when a service is
down, the built-in lists (funbot_data) answer instead.

Sources: JokeAPI (safe mode: no NSFW, religious, political, racist, sexist or explicit jokes; no 'Dark' category), Official Joke API,
icanhazdadjoke, catfact.ninja and meowfacts.  Each lookup fetches a batch where the service allows it, so most
answers need no lookup at all."""
import random
import re
import threading
import zlib

import funbot_data as data
import meshbot_common as mc

UA = {"User-Agent": "mcIRC fun bot (github.com/bclml/mcIRC)", "Accept": "application/json"}
MAX_LEN = 220                   # two mesh messages at most (the bot answers in up to 2 parts)
REMEMBER = 400                  # told lately, per kind: not told again until this many others were
# words that never go out over the mesh, whatever a collection lets through
_BAD = re.compile(r"\b(?:sex\w*|porn\w*|nud\w*|naked|drunk\w*|beer|vodka|kill\w*|dead|die[ds]?|suicid\w*|gun\w*|nazi\w*|hitler|"
                  r"damn|hell|crap|ass|bitch\w*|bastard\w*|shit\w*|fuck\w*|god|jesus|allah|religio\w*|church|wife|wives|blonde\w*|"
                  r"aids|hiv|cancer\w*|disease\w*|tumou?r\w*|euthan\w*|poison\w*|death\w*|corpse\w*|funeral\w*|cemeter\w*)\b", re.I)


def _jokeapi(get):
    d = get("https://v2.jokeapi.dev/joke/Misc,Programming,Pun,Spooky,Christmas",
            {"safe-mode": "", "blacklistFlags": "nsfw,religious,political,racist,sexist,explicit", "amount": 10}, headers=UA)
    return [j["joke"] if j.get("type") == "single" else f"{j['setup']} - {j['delivery']}" for j in d.get("jokes", []) if not d.get("error")]


def _official(get):
    return [f"{j['setup']} - {j['punchline']}" for j in get("https://official-joke-api.appspot.com/jokes/ten", headers=UA)]


def _dadjokes(get):
    d = get("https://icanhazdadjoke.com/search", {"limit": 30, "page": random.randint(1, 24)}, headers=UA)
    return [j["joke"] for j in d.get("results", [])]


def _catninja(get):
    d = get("https://catfact.ninja/facts", {"limit": 20, "page": random.randint(1, 16), "max_length": MAX_LEN}, headers=UA)
    return [f["fact"] for f in d.get("data", [])]


def _meow(get):
    return get("https://meowfacts.herokuapp.com/", {"count": 10}, headers=UA).get("data", [])


SOURCES = {"joke": (_jokeapi, _official), "dadjoke": (_dadjokes,), "catfact": (_catninja, _meow)}
OFFLINE = {"joke": data.JOKES, "dadjoke": data.DADJOKES, "catfact": data.CATFACTS}


def tag(text): return zlib.crc32(re.sub(r"\W+", "", text.lower()).encode())


def clean(text):
    """One line, fit for the mesh - or None (too long, or a word that doesn't go out)."""
    t = re.sub(r"\s+", " ", (text or "").replace("’", "'").replace("“", '"').replace("”", '"')).strip()
    return t if t and len(t) <= MAX_LEN and not _BAD.search(t) else None


class Teller:
    """Hands out jokes / facts of a kind that weren't told lately.  told: {kind: [tags]} - kept by the caller (the bot's settings)."""

    def __init__(self, told=None, get=mc.http_json):
        self.told = {k: list(v)[-REMEMBER:] for k, v in (told or {}).items()}
        self.ready = {k: [] for k in SOURCES}             # fetched, not told yet
        self.get, self.lock = get, threading.Lock()

    def _fresh(self, kind, texts):
        seen = set(self.told.get(kind, []))
        return [t for t in dict.fromkeys(c for c in map(clean, texts) if c) if tag(t) not in seen]

    def next(self, kind, online=True):
        """A joke / fact of this kind (blocking: the bot calls it in the background)."""
        with self.lock: waiting = self._fresh(kind, self.ready[kind])
        tries = list(SOURCES[kind]) * 2 if online else []
        random.shuffle(tries)
        while not waiting and tries:
            try: got = tries.pop()(self.get)
            except Exception: continue                  # that service is down / slow: the next one, else the built-in ones
            with self.lock:
                self.ready[kind] = self._fresh(kind, self.ready[kind] + got)
                waiting = self.ready[kind]
        if not waiting:                                   # offline: the built-in list, the least lately told first
            waiting = self._fresh(kind, OFFLINE[kind]) or list(OFFLINE[kind])
        text = random.choice(waiting)
        with self.lock:
            if text in self.ready[kind]: self.ready[kind].remove(text)
            self.told.setdefault(kind, []).append(tag(text))
            self.told[kind] = self.told[kind][-REMEMBER:]
        return text
