Param(
   [Switch]
   $init,

   [Switch]
   $refresh,

   [Switch]
   $refreshbgg,

   [Switch]
   $run
)

$env:FLASK_APP = "main:app"
$env:FLASK_ENV = "development"
if ($init) {
   uv run flask init-db
}
if ($refreshbgg) {
   uv run flask refresh-bgg
}
if ($refresh) {
   uv run flask refresh-db
}
if ($run) {
   uv run flask run
}
