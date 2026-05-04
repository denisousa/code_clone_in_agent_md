from omniccg.code_operations import get_code_without_comments_and_blank_lines
from omniccg.hash_operations import generate_simhash, match_hashes

class CloneFragment:
    def __init__(self, file, ls, le):
        # replace /dataset/production with /repo to keep compatibility with the original pipeline
        self.file = file.replace("/dataset/production", "/repo")
        self.ls = ls
        self.le = le
        self.code_content = get_code_without_comments_and_blank_lines(file, ls, le)
        self.hash = generate_simhash(self.code_content)

    def contains(self, other):
        return self.file == other.file and self.ls <= other.ls and self.le >= other.le

    def __eq__(self, other):
        return self.file == other.file and self.ls == other.ls and self.le == other.le

    def matches(self, other):
        if self.file == other.file and self.ls == other.ls and self.le == other.le:
            return True

        matches_result, _ = match_hashes(self.hash, other.hash, threshold=0.90)
        return matches_result

    def matchesStrictly(self, other):
        matches_result, _ = match_hashes(self.hash, other.hash, threshold=1.0)
        return self.file == other.file and matches_result

    def __hash__(self):
        return hash(self.file + str(self.ls))

    def toXML(self):
        return '\t\t\t<source file="%s" startline="%d" endline="%d" hash="%d"></source>\n' % (self.file, self.ls, self.le, self.hash)

    def countLOC(self):
        return self.le - self.ls
