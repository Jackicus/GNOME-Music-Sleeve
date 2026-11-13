# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

# The development build is "Music Sleeve (Development)" in the desktop file and the metainfo,
# as GNOME's development builds are, so it is told from a release install beside it. The
# suffix goes after each name once the translations are merged
# (build-aux/meson/name-suffix.py), so the template's msgid is the name alone and the merge
# finds it translated. The Flatpak manifest adds no suffix of its own.
name_suffix = get_option('profile') == 'development' ? ' (Development)' : ''
data_configuration = {'APP_ID': application_id}
python3 = python.find_installation('python3')
add_name_suffix = [python3, files('..' / 'build-aux' / 'meson' / 'name-suffix.py'),
                   '@INPUT@', '@OUTPUT@', name_suffix]

desktop_file = custom_target(
  input: i18n.merge_file(
    input: configure_file(
      input: base_id + '.desktop.in',
      output: application_id + '.desktop.in',
      configuration: data_configuration,
    ),
    output: application_id + '.desktop.merged',
    type: 'desktop',
    po_dir: '../po',
  ),
  output: application_id + '.desktop',
  command: add_name_suffix,
  install: true,
  install_dir: get_option('datadir') / 'applications',
)

metainfo_file = custom_target(
  input: i18n.merge_file(
    input: configure_file(
      input: base_id + '.metainfo.xml.in',
      output: application_id + '.metainfo.xml.in',
      configuration: data_configuration,
    ),
    output: application_id + '.metainfo.xml.merged',
    po_dir: '../po',
  ),
  output: application_id + '.metainfo.xml',
  command: add_name_suffix,
  install: true,
  install_dir: get_option('datadir') / 'metainfo',
)

# GNOME Shell's search provider (src/search_provider.py): the .ini tells the Shell the bus
# name and the object's path (under GApplication's own, the app ID with dots as slashes),
# and the D-Bus service file lets the bus start the app for a search, in service mode (no
# window until a result is activated). A launch from the Shell still runs the desktop file's
# Exec (DBusActivatable=false: a bus launch has no fallback when the bus cannot see the
# service file, docs/decisions.md). Both name this build's app ID.
search_provider_configuration = data_configuration + {
  'OBJECT_PATH': '/' + application_id.replace('.', '/') + '/SearchProvider',
  'BINDIR': get_option('prefix') / get_option('bindir'),
}
configure_file(
  input: base_id + '.search-provider.ini.in',
  output: application_id + '.search-provider.ini',
  configuration: search_provider_configuration,
  install: true,
  install_dir: get_option('datadir') / 'gnome-shell' / 'search-providers',
)
configure_file(
  input: base_id + '.service.in',
  output: application_id + '.service',
  configuration: search_provider_configuration,
  install: true,
  install_dir: get_option('datadir') / 'dbus-1' / 'services',
)

install_data(
  base_id + '.gschema.xml',
  install_dir: get_option('datadir') / 'glib-2.0' / 'schemas',
)

# The development build gets the striped icon, installed under its own .Devel name.
app_icon = get_option('profile') == 'development' ? base_id + '-devel.svg' : base_id + '.svg'
install_data(
  'icons' / app_icon,
  rename: application_id + '.svg',
  install_dir: get_option('datadir') / 'icons' / 'hicolor' / 'scalable' / 'apps',
)
install_data(
  'icons' / base_id + '-symbolic.svg',
  rename: application_id + '-symbolic.svg',
  install_dir: get_option('datadir') / 'icons' / 'hicolor' / 'symbolic' / 'apps',
)

desktop_file_validate = find_program('desktop-file-validate', required: false)
if desktop_file_validate.found()
  test('validate-desktop', desktop_file_validate, args: [desktop_file])
endif

appstreamcli = find_program('appstreamcli', required: false)
if appstreamcli.found()
  test('validate-metainfo', appstreamcli,
    args: ['validate', '--no-net', '--explain', metainfo_file])
endif

glib_compile_schemas = find_program('glib-compile-schemas', required: false)
if glib_compile_schemas.found()
  test('validate-schema', glib_compile_schemas,
    args: ['--strict', '--dry-run', meson.current_source_dir()])
endif
