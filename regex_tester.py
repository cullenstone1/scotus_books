import re
import constants

def findAndPrint(regex):
  with open("parsedOutput", "r") as f:
    citations = re.findall(regex, f.read())
    for citation in citations:
      print(citation) 

if __name__ == '__main__':
  for x in constants.citationRegexes:
    findAndPrint(x)