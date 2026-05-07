# SPDX-License-Identifier: AGPL-3.0-only
import strutils, uri, std/options

import jester

import router_utils
import ".."/[query, types, api, formatters]
import ../views/[general, search]

include "../views/opensearch.nimf"

export search

proc createSearchRouter*(cfg: Config) =
  router search:
    get "/search/?":
      let q = @"q"
      if q.len > 500:
        resp Http400, showError("Search input too long.", cfg)

      let
        prefs = requestPrefs()
        query = initQuery(params(request))
        title = "Search" & (if q.len > 0: " (" & q & ")" else: "")

      case query.kind
      of users:
        if "," in q:
          redirect("/" & q)
        var users: Result[User]
        try:
          users = await getGraphUserSearch(query, getCursor())
        except InternalError:
          users = Result[User](beginning: true, query: query)
        resp renderMain(renderUserSearch(users, prefs), request, cfg, prefs, title)
      of tweets:
        let
          timeline = await getGraphTweetSearch(query, getCursor())
          rss = if cfg.enableRSSSearch: "/search/rss?" & genQueryUrl(query) else: ""
        resp renderMain(renderTweetSearch(timeline, prefs, getPath()),
                        request, cfg, prefs, title, rss=rss)
      else:
        resp Http404, showError("Invalid search", cfg)

    get "/search.json":
      let q = @"q"
      if q.len > 500:
        resp Http400, "Search input too long."

      let
        queryTable = params(request)
        query = initQuery(queryTable)
        product = @"p".capitalizeAscii
        validProducts = ["Latest", "Top", "People", "Photos", "Videos"]
        searchProduct = if product in validProducts: product else: "Latest"

      # Force tweet search kind for this endpoint unless specified
      var finalQuery = query
      if "f" notin queryTable:
        finalQuery.kind = tweets

      try:
        let timeline = await getGraphTweetSearch(finalQuery, getCursor(), searchProduct)
        respSearchJson(timeline)
      except:
        resp Http500, "{\"error\": \"Instance has no auth tokens, or is fully rate limited.\"}", "application/json"

    get "/hashtag/@hash":
      redirect("/search?f=tweets&q=" & encodeUrl("#" & @"hash"))

    get "/opensearch":
      let url = getUrlPrefix(cfg) & "/search?f=tweets&q="
      resp Http200, {"Content-Type": "application/opensearchdescription+xml"},
                     generateOpenSearchXML(cfg.title, cfg.hostname, url)
