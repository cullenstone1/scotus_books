import sys
from pdfminer import high_level
from pdfminer.high_level import extract_pages
from pdfminer.high_level import extract_text
from pdfminer.layout import LTTextContainer, LTChar, LTTextLine, LTLine
import constants

listOfFonts = []

def ExtractFullText(pdfPath):
  text = extract_text(pdfPath)
  with open(pdfPath[:-4]+ ".txt", "w") as f:
    f.write(text)

def ExtractTextByPage(pdfPath):
  textByPage = []
  pages = list(extract_pages(pdfPath))
  for pageLayout in pages:
    line_pos = 0.0
    page_text = ""
    for element in pageLayout:
      if isinstance(element, LTLine):
        # height of line on page
        line_pos = element.y0
    for element in pageLayout:
      if isinstance(element, LTTextContainer):
        if element.y0 > line_pos:
          page_text += element.get_text()
    textByPage.append(page_text)

  return textByPage

def returnPageNums(filename, match):
  textByPage = ExtractTextByPage(filename)
  switchFlipped = False
  listOfPages = []
  done = False
  i = 0
  while not done:
    present = match in textByPage[i].lower()
    if present:
      listOfPages.append(i)
      switchFlipped = True
    if not present and switchFlipped:
      done = True
    i += 1
  return listOfPages
    
def isFootnote(element, threshold=15):
  with open("output.txt", "a") as f:
    for line in element:
      if isinstance(line, LTTextLine):
        for char in line:
          if isinstance(char, LTChar):
            f.write(f"{char.size:06.2f}\t{char}\n")
            # if char.fontname not in listOfFonts:
              # listOfFonts.append(char.fontname)
            # if char.fontname == "AAAAAG+CenturyExpanded":
            if char.fontname == "AAAAAG+CenturyExpanded" and char.size > constants.opinionFontSize - 0.1 and char.size < constants.opinionFontSize + 0.1:
              return True
      return False


if __name__ == '__main__':
  fname = sys.argv[1]
  text = ExtractTextByPage(fname)
  # text = ExtractFullText(fname)
  with open("parsedOutput", "w") as f:
    for x in text:
      f.write(x)