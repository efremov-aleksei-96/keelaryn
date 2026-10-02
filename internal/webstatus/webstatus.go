package webstatus

import (
	"bytes"
	"context"
	"embed"
	"encoding/json"
	"errors"
	"fmt"
	"html/template"
	"io"
	"net"
	"net/http"
	"strings"
	"time"

	"github.com/efremov-aleksei-96/keelaryn/internal/controlstorage"
	"github.com/efremov-aleksei-96/keelaryn/internal/doctor"
)

const (
	DefaultListenAddress = "127.0.0.1:0"
	diagnosticTimeout     = 30 * time.Second
	responseWriteTimeout  = 40 * time.Second
)

var (
	ErrInvalidOptions    = errors.New("invalid web status options")
	ErrNonLoopbackListen = errors.New("web status listener must use a literal loopback IP")
)

//go:embed static/status.html static/status.css
var embeddedAssets embed.FS

var statusTemplate = template.Must(template.ParseFS(embeddedAssets, "static/status.html"))

type Options struct {
	ControlDir string
	Listen     string
}

type handler struct {
	controlDir string
	diagnostic chan struct{}
	runDoctor  func(context.Context, string) doctor.Report
}

type pageData struct {
	Report doctor.Report
}

func NewHandler(controlDir string) (http.Handler, error) {
	if strings.TrimSpace(controlDir) == "" {
		return nil, ErrInvalidOptions
	}
	layout, err := controlstorage.OpenExisting(controlDir)
	if err != nil {
		return nil, err
	}
	h := &handler{
		controlDir: layout.Dir,
		diagnostic: make(chan struct{}, 1),
		runDoctor:  doctor.Run,
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/", h.servePage)
	mux.HandleFunc("/api/status", h.serveAPI)
	mux.HandleFunc("/assets/status.css", h.serveCSS)
	return securityHeaders(fetchMetadataOnly(localHostOnly(mux))), nil
}

func Run(ctx context.Context, options Options, announce io.Writer) error {
	if ctx == nil {
		return ErrInvalidOptions
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	listen := strings.TrimSpace(options.Listen)
	if listen == "" {
		listen = DefaultListenAddress
	}
	if err := validateLoopbackListenAddress(listen); err != nil {
		return err
	}
	handler, err := NewHandler(options.ControlDir)
	if err != nil {
		return err
	}
	listener, err := net.Listen("tcp", listen)
	if err != nil {
		return fmt.Errorf("listen for web status: %w", err)
	}
	if !listenerIsLoopback(listener.Addr()) {
		_ = listener.Close()
		return ErrNonLoopbackListen
	}
	if announce != nil {
		if _, err := fmt.Fprintf(announce, "http://%s/\n", listener.Addr().String()); err != nil {
			_ = listener.Close()
			return fmt.Errorf("announce web status address: %w", err)
		}
	}

	server := &http.Server{
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       5 * time.Second,
		WriteTimeout:      responseWriteTimeout,
		IdleTimeout:       30 * time.Second,
		MaxHeaderBytes:    16 << 10,
	}

	shutdownStop := make(chan struct{})
	shutdownDone := make(chan struct{})
	go func() {
		defer close(shutdownDone)
		select {
		case <-ctx.Done():
			shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			_ = server.Shutdown(shutdownCtx)
		case <-shutdownStop:
		}
	}()

	serveErr := server.Serve(listener)
	close(shutdownStop)
	<-shutdownDone
	if errors.Is(serveErr, http.ErrServerClosed) && ctx.Err() != nil {
		return nil
	}
	if serveErr != nil {
		return fmt.Errorf("serve web status: %w", serveErr)
	}
	return nil
}

func validateLoopbackListenAddress(address string) error {
	host, port, err := net.SplitHostPort(address)
	if err != nil || port == "" {
		return ErrInvalidOptions
	}
	ip := net.ParseIP(strings.Trim(host, "[]"))
	if ip == nil || !ip.IsLoopback() {
		return ErrNonLoopbackListen
	}
	return nil
}

func listenerIsLoopback(address net.Addr) bool {
	tcp, ok := address.(*net.TCPAddr)
	return ok && tcp.IP != nil && tcp.IP.IsLoopback()
}

func fetchMetadataOnly(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Add("Vary", "Sec-Fetch-Site")
		switch strings.ToLower(strings.TrimSpace(r.Header.Get("Sec-Fetch-Site"))) {
		case "", "same-origin", "none":
			next.ServeHTTP(w, r)
		default:
			http.Error(w, "forbidden", http.StatusForbidden)
		}
	})
}

func localHostOnly(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !requestHostIsLocal(r.Host) {
			http.Error(w, "forbidden", http.StatusForbidden)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func requestHostIsLocal(hostport string) bool {
	host := hostport
	if parsed, _, err := net.SplitHostPort(hostport); err == nil {
		host = parsed
	}
	host = strings.Trim(host, "[]")
	if strings.EqualFold(host, "localhost") {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("Content-Security-Policy", "default-src 'none'; style-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'")
		w.Header().Set("Referrer-Policy", "no-referrer")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("X-Frame-Options", "DENY")
		next.ServeHTTP(w, r)
	})
}

func methodAllowed(w http.ResponseWriter, r *http.Request) bool {
	if r.Method == http.MethodGet || r.Method == http.MethodHead {
		return true
	}
	w.Header().Set("Allow", "GET, HEAD")
	http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	return false
}

func (h *handler) diagnosticReport(ctx context.Context) (doctor.Report, bool) {
	select {
	case h.diagnostic <- struct{}{}:
		defer func() { <-h.diagnostic }()
	default:
		return doctor.Report{}, false
	}
	diagnosticCtx, cancel := context.WithTimeout(ctx, diagnosticTimeout)
	defer cancel()
	return h.runDoctor(diagnosticCtx, h.controlDir), true
}

func verificationBusy(w http.ResponseWriter) {
	w.Header().Set("Retry-After", "1")
	http.Error(w, "status verification busy", http.StatusServiceUnavailable)
}

func reportStatusCode(report doctor.Report) int {
	if report.Passed() {
		return http.StatusOK
	}
	return http.StatusServiceUnavailable
}

func (h *handler) serveAPI(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/api/status" {
		http.NotFound(w, r)
		return
	}
	if !methodAllowed(w, r) {
		return
	}
	report, ok := h.diagnosticReport(r.Context())
	if !ok {
		verificationBusy(w)
		return
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(reportStatusCode(report))
	if r.Method == http.MethodHead {
		return
	}
	_ = json.NewEncoder(w).Encode(report)
}

func (h *handler) servePage(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		http.NotFound(w, r)
		return
	}
	if !methodAllowed(w, r) {
		return
	}
	report, ok := h.diagnosticReport(r.Context())
	if !ok {
		verificationBusy(w)
		return
	}
	var rendered bytes.Buffer
	if err := statusTemplate.Execute(&rendered, pageData{Report: report}); err != nil {
		http.Error(w, "status rendering failed", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(reportStatusCode(report))
	if r.Method == http.MethodHead {
		return
	}
	_, _ = w.Write(rendered.Bytes())
}

func (h *handler) serveCSS(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/assets/status.css" {
		http.NotFound(w, r)
		return
	}
	if !methodAllowed(w, r) {
		return
	}
	css, err := embeddedAssets.ReadFile("static/status.css")
	if err != nil {
		http.Error(w, "asset unavailable", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "text/css; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	if r.Method == http.MethodHead {
		return
	}
	_, _ = w.Write(css)
}
