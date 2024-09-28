import sys
import re
import constants

opinionFound = False
concurenceFound = False
dissentFound = False
numConcurrences = 0

def separateOpinions():
  with open(sys.argv[1], "r") as f:
    for line in f:
      if re.match(r'Justice\s+\w+\s+delivered', line):
        opinionFound = True
        print(line)
      if re.match(r'Justice\s+\w+,\s+concurring', line):
        opinionFound = False
        concurenceFound = True
        numConcurrences += 1
      if opinionFound:
        with open(sys.argv[1][:-4] + "_opinion.txt", "a") as of:
          of.write(line)
      if concurenceFound:
        s = f"_concurring{numConcurrences}.txt"
        with open(sys.argv[1][:-4] + s, "a") as of:
          of.write(line)

def removeCitations():
  with open(sys.argv[1], "r") as f:
    with open(sys.argv[1][:-4] + "_footnotes_removed.txt", "w") as f2:
      text = f.read()
      for exp in constants.expressions:
        l = re.findall(constants.expressions[exp], text)
        print(l)
        text = re.sub(constants.expressions[exp], '', text, re.DOTALL)
      # text = re.sub(pattern1, '', text)
      f2.write(text)
  
  # with open(sys.argv[1][:-4] + "_footnotes_removed.txt", "r") as f2:
    # text = f2.read()
    # text = re.sub(constants.expressions["line_end_hyphen"], '', text, re.DOTALL)
  # with open(sys.argv[1][:-4] + "_footnotes_removed.txt", "w") as f2:
    # f2.write(text)
  

if __name__ == '__main__':
  removeCitations()