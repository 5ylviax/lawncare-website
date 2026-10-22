package main

import "net/http"

func (app *App) routes() *http.ServeMux {
	mux := http.NewServeMux()

	mux.Handle("/static/", http.StripPrefix("/static", http.FileServer(http.Dir("static"))))
	mux.HandleFunc("/", app.handleIndex)
	return mux
}
