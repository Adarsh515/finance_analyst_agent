from bs4 import BeautifulSoup

with open("data/nvidia_10k.htm", "r", encoding="utf-8") as file:
    html = file.read()

soup = BeautifulSoup(html, "html.parser")

#You can also use the faster lxml parser if it's installed
#soup = BeautifulSoup(html, "lxml")
text = soup.get_text(separator=" ")
print(len(text))
print(text[:500])

i = text.find("Consolidated Statements of Income")
print(text[i:i+700])