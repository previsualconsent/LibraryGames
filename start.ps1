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

$env:FLASK_APP = "LibraryGames"
$env:FLASK_ENV = "development"
if ($init) {
   flask init-db
}
if ($refreshbgg) {
   flask refresh-bgg
}
if ($refresh) {
   flask refresh-db
}
if ($run) {
   flask run
}
