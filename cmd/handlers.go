package main

import (
	"html/template"
	"net/http"
)

// tmpl, err := template.New("test")

func (app *App) handleIndex(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		http.NotFound(w, r)
		return
	}

	files := []string{
		"./templates/index.html",
		"./templates/partials/nav.html",
		"./templates/partials/thankyou.html",
	}

	ts, err := template.ParseFiles(files...)

	if err != nil {
		app.serverError(w, err)
		return
	}

	err = ts.ExecuteTemplate(w, "index", nil)
	if err != nil {
		app.serverError(w, err)
	}
}
