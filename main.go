package main

import (
	"log"
	"net/http"
)

func home(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		http.NotFound(w, r)
		return
	}

	w.Write([]byte("Welcome to lawn care website!"))
}
func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("/", home)

	log.Print("Starting server on :8080")
	err := http.ListenAndServe(":8080", mux) // host:port ---> localhost::4000

	log.Fatal(err)

}
