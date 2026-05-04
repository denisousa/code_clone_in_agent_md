from typing import List
from omniccg.CloneFragment import CloneFragment

class CloneClass:
    def __init__(self):
        self.fragments: List[CloneFragment] = []

    def contains(self, fragment):
        for f in self.fragments:
            if f.matches(fragment):
                return True
        return False

    def matches(self, cc: "CloneClass"):
        n = 0
        for fragment in cc.fragments:
            if self.contains(fragment):
                n += 1
        return (n == len(cc.fragments)) or (n == len(self.fragments))

    def toXML(self):
        s = '\t\t<class nclones="%d">\n' % (len(self.fragments))
        for fragment in self.fragments:
            try:
                s += fragment.toXML()
            except Exception:
                pass
        s += "\t\t</class>\n"
        return s

    def countLOC(self):
        return sum(f.countLOC() for f in self.fragments)
