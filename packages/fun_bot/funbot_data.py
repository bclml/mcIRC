"""Built-in texts for the fun bot (no internet needed): Magic 8-Ball answers, jokes, dad jokes, cat facts and the hacker-jargon generator.
All short enough for one mesh message."""
import random

MAGIC8 = ["It is certain.", "It is decidedly so.", "Without a doubt.", "Yes, definitely.", "You may rely on it.", "As I see it, yes.",
          "Most likely.", "Outlook good.", "Yes.", "Signs point to yes.", "Reply hazy, try again.", "Ask again later.",
          "Better not tell you now.", "Cannot predict now.", "Concentrate and ask again.", "Don't count on it.", "My reply is no.",
          "My sources say no.", "Outlook not so good.", "Very doubtful."]

JOKES = [
    "I told my radio a joke. It didn't laugh - no reception.",
    "Why did the LoRa packet go to therapy? Too many hops in its past.",
    "There are 10 kinds of people: those who know binary and those who don't.",
    "My antenna and I are in a long-distance relationship. It works great.",
    "Why do programmers prefer dark mode? Light attracts bugs.",
    "I'd tell you a UDP joke, but you might not get it.",
    "What do you call a mesh with no nodes? A hole.",
    "The repeater said: I'm not saying it again. Then it did. Twice.",
    "Why was the battery so calm? It knew how to stay positive.",
    "I asked the weather station for a joke. It was a little dry.",
    "Why don't satellites ever get lost? They always follow their orbit-uary.",
    "A TCP packet walks into a bar: I'd like a beer. Bartender: You'd like a beer? TCP: Yes, a beer.",
    "Why did the router break up with the switch? It needed more space - a whole subnet.",
    "Never trust an atom. They make up everything.",
    "What did the ocean say to the beach? Nothing, it just waved.",
    "I bought a ceiling fan. It's my biggest fan.",
    "The rotating antenna was a hit. Everyone said it had real direction.",
    "What's a ham radio operator's favourite food? A QSO-sage roll.",
    "My GPS and I broke up. It kept telling me where to go.",
    "Why are frogs so happy? They eat whatever bugs them.",
    "Why did the coffee file a police report? It got mugged.",
    "I'm reading a book on anti-gravity. I can't put it down.",
    "Why did the scarecrow get promoted? He was outstanding in his field.",
    "Parallel lines have so much in common. It's a shame they'll never meet.",
]

DADJOKES = [
    "I'm afraid for the calendar. Its days are numbered.",
    "Why do fathers take an extra pair of socks golfing? In case they get a hole in one.",
    "What do you call a fake noodle? An impasta.",
    "I only know 25 letters of the alphabet. I don't know y.",
    "What did the zero say to the eight? Nice belt.",
    "Why can't a nose be 12 inches long? Then it would be a foot.",
    "I used to hate facial hair, but then it grew on me.",
    "What do you call a fish wearing a bowtie? Sofishticated.",
    "How do you follow Will Smith in the snow? You follow the fresh prints.",
    "What do you call a factory that makes okay products? A satisfactory.",
    "Why did the bicycle fall over? It was two tired.",
    "What time did the man go to the dentist? Tooth hurt-y.",
    "I would avoid the sushi if I were you. It's a little fishy.",
    "Want to hear a joke about construction? I'm still working on it.",
    "What do you call a deer with no eyes? No idea.",
    "Why don't eggs tell jokes? They'd crack each other up.",
    "How does a penguin build its house? Igloos it together.",
    "Did you hear about the restaurant on the moon? Great food, no atmosphere.",
    "Why did the math book look sad? It had too many problems.",
    "What do you call a sleeping bull? A bulldozer.",
    "I'm on a seafood diet. I see food and I eat it.",
    "What do you call cheese that isn't yours? Nacho cheese.",
    "Why couldn't the leopard play hide and seek? He was always spotted.",
    "How do you make a tissue dance? Put a little boogie in it.",
    "What did one wall say to the other? I'll meet you at the corner.",
]

CATFACTS = [
    "Cats sleep 12 to 16 hours a day.",
    "A group of cats is called a clowder.",
    "Cats have five toes on their front paws but only four on the back.",
    "A cat's nose print is unique, like a human fingerprint.",
    "Cats can rotate their ears 180 degrees.",
    "Adult cats meow mostly to talk to people, rarely to other cats.",
    "A cat's purr vibrates at about 25 to 150 Hz.",
    "Cats can't taste sweetness.",
    "A cat's whiskers are about as wide as its body.",
    "Most cats are lactose intolerant - milk is not a good treat.",
    "Cats have a third eyelid called the nictitating membrane.",
    "A cat can jump about six times its own length.",
    "Cats spend up to a third of their waking hours grooming.",
    "The oldest known pet cat was found in a 9,500-year-old grave in Cyprus.",
    "Cats have 32 muscles in each ear.",
    "A cat's heart beats about twice as fast as a human's.",
    "Kittens start dreaming at about one week old.",
    "Cats can make over 100 different sounds; dogs about 10.",
    "A cat's spine has about 53 vertebrae - very bendy.",
    "Cats sweat only through their paw pads.",
    "Orange cats are mostly male: about 80 percent.",
    "A cat's field of view is about 200 degrees; ours is about 180.",
]

_ADJ = ["auxiliary", "primary", "back-end", "digital", "open-source", "virtual", "cross-platform", "redundant", "online", "haptic", "multi-byte",
        "bluetooth", "wireless", "1080p", "neural", "optical", "solid state", "mobile", "LoRa", "mesh"]
_ABBR = ["TCP", "HTTP", "SDD", "RAM", "GB", "CSS", "SSL", "AGP", "SQL", "FTP", "PCI", "AI", "ADP", "RSS", "XML", "EXE", "COM", "HDD", "THX", "SMTP",
         "SMS", "USB", "PNG", "SNR", "RSSI"]
_NOUN = ["driver", "protocol", "bandwidth", "panel", "microchip", "program", "port", "card", "array", "interface", "system", "sensor", "firewall",
         "hard drive", "pixel", "alarm", "feed", "monitor", "application", "transmitter", "bus", "circuit", "capacitor", "matrix", "repeater", "antenna"]
_VERB = ["back up", "bypass", "hack", "override", "compress", "copy", "navigate", "index", "connect", "generate", "quantify", "calculate",
         "synthesize", "input", "transmit", "program", "reboot", "parse", "flash"]
_ING = ["backing up", "bypassing", "hacking", "overriding", "compressing", "copying", "navigating", "indexing", "connecting", "generating",
        "quantifying", "calculating", "synthesizing", "transmitting", "programming", "parsing", "flashing"]
_TEMPLATES = [
    "If we {verb} the {noun}, we can get to the {abbr} {noun} through the {adj} {abbr} {noun}!",
    "We need to {verb} the {adj} {abbr} {noun}!",
    "Try to {verb} the {abbr} {noun}, maybe it will {verb} the {adj} {noun}!",
    "You can't {verb} the {noun} without {ing} the {adj} {abbr} {noun}!",
    "Use the {adj} {abbr} {noun}, then you can {verb} the {adj} {noun}!",
    "The {abbr} {noun} is down, {verb} the {adj} {noun} so we can {verb} the {abbr} {noun}!",
    "{ing} the {noun} won't do anything, we need to {verb} the {adj} {abbr} {noun}!",
    "I'll {verb} the {adj} {abbr} {noun}, that should {noun} the {abbr} {noun}!",
]


def hacker(rng=random):
    """One line of movie-style hacker jargon."""
    pick = lambda xs: rng.choice(xs)
    while True:
        t = pick(_TEMPLATES)
        out = t
        for key, pool in (("{verb}", _VERB), ("{noun}", _NOUN), ("{adj}", _ADJ), ("{abbr}", _ABBR), ("{ing}", _ING)):
            while key in out: out = out.replace(key, pick(pool), 1)
        out = out[0].upper() + out[1:]
        if len(out) <= 110: return out
