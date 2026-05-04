from typing import List
from omniccg.CloneFragment import CloneFragment

class CloneVersion:
    def __init__(self, cc=None, h=None, n=None, author="", evo="None", chan="None", n_evo=0, n_change=0, clones_loc=0, commit_date=""):
        self.cloneclass = cc
        self.hash = h
        self.nr = n
        self.evolution_pattern = evo
        self.change_pattern = chan
        self.removed_fragments: List[CloneFragment] = []
        self.author = author
        self.n_evo = n_evo
        self.n_change = n_change
        self.clones_loc = clones_loc
        self.commit_date = commit_date

    def toXMLRemoved(self):
        s = ""
        for f in self.removed_fragments:
            s += f.toXML()
        return s

    def toXML(self):
        s = '\t<version nr="%d" hash="%s" evolution="%s" change="%s" author="%s" n_evo="%d" n_cha="%d" clones_LOC="%d" commit_date="%s" >\n' % (
            self.nr,
            self.hash,
            self.evolution_pattern,
            self.change_pattern,
            self.author,
            self.n_evo,
            self.n_change,
            self.clones_loc,
            self.commit_date,
        )

        try:
            s += self.cloneclass.toXML()
        except Exception:
            pass
        s += "\t</version>\n"
        if self.removed_fragments:
            s += self.toXMLRemoved()
        return s
