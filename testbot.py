# -*- coding: utf-8  -*-
import sys
sys.path.append('/Users/nicolasnoe/pywikibot')

import pywikibot
site = pywikibot.Site("en", "wikipedia")
page = pywikibot.Page(site, u"Douglas Adams")
item = pywikibot.ItemPage.fromPage(page)
dictionary = item.get()
print(dictionary)
print(dictionary.keys())
print(item)