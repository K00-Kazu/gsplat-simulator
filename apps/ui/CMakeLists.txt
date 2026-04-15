cmake_minimum_required(VERSION 3.21)

if(POLICY CMP0144)
    cmake_policy(SET CMP0144 NEW)
endif()

project(gsplat_ui LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

get_filename_component(GSPLAT_REPO_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../.." ABSOLUTE)
set(GSPLAT_UI_LOCAL_ZENOHC_ROOT "${GSPLAT_REPO_ROOT}/third_party/zenoh/windows/zenohc")
set(GSPLAT_UI_LOCAL_ZENOHCXX_ROOT "${GSPLAT_REPO_ROOT}/third_party/zenoh/windows/zenohcxx")
file(TO_CMAKE_PATH "${GSPLAT_REPO_ROOT}/config/transport.dev.json" GSPLAT_UI_TRANSPORT_CONFIG_PATH)
set(GSPLAT_UI_SRC_DIR "${CMAKE_CURRENT_SOURCE_DIR}/src")

function(gsplat_ui_define_zenohc_imported_target zenohc_root)
    set(zenohc_lib_candidates
        "${zenohc_root}/lib/zenohc.dll.lib"
        "${zenohc_root}/lib/zenohc.lib"
        "${zenohc_root}/debug/target/debug/zenohc.lib"
        "${zenohc_root}/debug/target/debug/zenohc.dll.lib"
        "${zenohc_root}/debug/target/debug/deps/zenohc.lib"
        "${zenohc_root}/debug/target/debug/deps/zenohc.dll.lib"
        "${zenohc_root}/release/target/release/zenohc.lib"
        "${zenohc_root}/release/target/release/zenohc.dll.lib"
        "${zenohc_root}/release/target/release/deps/zenohc.lib"
        "${zenohc_root}/release/target/release/deps/zenohc.dll.lib"
    )
    set(zenohc_dll_candidates
        "${zenohc_root}/bin/zenohc.dll"
        "${zenohc_root}/debug/target/debug/zenohc.dll"
        "${zenohc_root}/debug/target/debug/deps/zenohc.dll"
        "${zenohc_root}/release/target/release/zenohc.dll"
        "${zenohc_root}/release/target/release/deps/zenohc.dll"
    )
    set(zenohc_include_candidates
        "${zenohc_root}/include"
        "${zenohc_root}/debug/include"
        "${zenohc_root}/debug/target/debug/include"
        "${zenohc_root}/release/include"
        "${zenohc_root}/release/target/release/include"
    )

    set(zenohc_import_lib "")
    foreach(candidate IN LISTS zenohc_lib_candidates)
        if(EXISTS "${candidate}")
            set(zenohc_import_lib "${candidate}")
            break()
        endif()
    endforeach()

    set(zenohc_runtime_dll "")
    foreach(candidate IN LISTS zenohc_dll_candidates)
        if(EXISTS "${candidate}")
            set(zenohc_runtime_dll "${candidate}")
            break()
        endif()
    endforeach()

    set(zenohc_include_dir "")
    foreach(candidate IN LISTS zenohc_include_candidates)
        if(EXISTS "${candidate}/zenoh.h")
            set(zenohc_include_dir "${candidate}")
            break()
        endif()
    endforeach()

    if(zenohc_import_lib AND zenohc_include_dir AND NOT TARGET zenohc::lib)
        add_library(zenohc::lib SHARED IMPORTED GLOBAL)
        set_target_properties(
            zenohc::lib PROPERTIES
            IMPORTED_IMPLIB "${zenohc_import_lib}"
            INTERFACE_INCLUDE_DIRECTORIES "${zenohc_include_dir}"
        )

        if(zenohc_runtime_dll)
            set_target_properties(zenohc::lib PROPERTIES IMPORTED_LOCATION "${zenohc_runtime_dll}")
        endif()
    endif()
endfunction()

function(gsplat_ui_define_zenohcxx_zenohc_target zenohcxx_root)
    set(zenohcxx_include_candidates
        "${zenohcxx_root}/include"
        "${zenohcxx_root}"
    )

    set(zenohcxx_include_dir "")
    foreach(candidate IN LISTS zenohcxx_include_candidates)
        if(EXISTS "${candidate}/zenoh.hxx")
            set(zenohcxx_include_dir "${candidate}")
            break()
        endif()
    endforeach()

    if(zenohcxx_include_dir AND NOT TARGET zenohcxx::zenohc)
        add_library(gsplat_ui_zenohcxx_zenohc INTERFACE)
        target_compile_definitions(gsplat_ui_zenohcxx_zenohc INTERFACE ZENOHCXX_ZENOHC)
        target_include_directories(gsplat_ui_zenohcxx_zenohc INTERFACE "${zenohcxx_include_dir}")
        target_link_libraries(gsplat_ui_zenohcxx_zenohc INTERFACE zenohc::lib)
        add_library(zenohcxx::zenohc ALIAS gsplat_ui_zenohcxx_zenohc)
    endif()
endfunction()

if(DEFINED ENV{QT_ROOT} AND NOT DEFINED Qt6_DIR)
    if(EXISTS "$ENV{QT_ROOT}/lib/cmake/Qt6")
        set(Qt6_DIR "$ENV{QT_ROOT}/lib/cmake/Qt6")
    else()
        list(PREPEND CMAKE_PREFIX_PATH "$ENV{QT_ROOT}")
    endif()
endif()

set(GSPLAT_UI_QT_PLUGINS_DIR "")
if(DEFINED ENV{QT_ROOT})
    if(EXISTS "$ENV{QT_ROOT}/plugins/platforms")
        set(GSPLAT_UI_QT_PLUGINS_DIR "$ENV{QT_ROOT}/plugins")
    elseif(EXISTS "$ENV{QT_ROOT}/../../../plugins/platforms")
        set(GSPLAT_UI_QT_PLUGINS_DIR "$ENV{QT_ROOT}/../../../plugins")
    endif()
endif()

if(NOT GSPLAT_UI_QT_PLUGINS_DIR AND DEFINED Qt6_DIR)
    if(EXISTS "${Qt6_DIR}/../../../plugins/platforms")
        set(GSPLAT_UI_QT_PLUGINS_DIR "${Qt6_DIR}/../../../plugins")
    endif()
endif()

set(GSPLAT_UI_ENABLE_ZENOH OFF CACHE BOOL "Enable zenoh smoke test support in the Qt UI")

include(CTest)

find_package(Qt6 REQUIRED COMPONENTS Widgets)

if(GSPLAT_UI_ENABLE_ZENOH)
    set(gsplat_ui_zenohc_root "")
    if(DEFINED ENV{ZENOHC_ROOT} AND NOT "$ENV{ZENOHC_ROOT}" STREQUAL "")
        set(gsplat_ui_zenohc_root "$ENV{ZENOHC_ROOT}")
    elseif(EXISTS "${GSPLAT_UI_LOCAL_ZENOHC_ROOT}")
        set(gsplat_ui_zenohc_root "${GSPLAT_UI_LOCAL_ZENOHC_ROOT}")
    endif()

    set(gsplat_ui_zenohcxx_root "")
    if(DEFINED ENV{ZENOHCXX_ROOT} AND NOT "$ENV{ZENOHCXX_ROOT}" STREQUAL "")
        set(gsplat_ui_zenohcxx_root "$ENV{ZENOHCXX_ROOT}")
    elseif(EXISTS "${GSPLAT_UI_LOCAL_ZENOHCXX_ROOT}/include/zenoh.hxx")
        set(gsplat_ui_zenohcxx_root "${GSPLAT_UI_LOCAL_ZENOHCXX_ROOT}")
    endif()

    if(gsplat_ui_zenohc_root AND NOT DEFINED zenohc_DIR)
        if(EXISTS "${gsplat_ui_zenohc_root}/lib/cmake/zenohc")
            set(zenohc_DIR "${gsplat_ui_zenohc_root}/lib/cmake/zenohc")
        elseif(EXISTS "${gsplat_ui_zenohc_root}/zenohcConfig.cmake")
            set(zenohc_DIR "${gsplat_ui_zenohc_root}")
        else()
            list(PREPEND CMAKE_PREFIX_PATH "${gsplat_ui_zenohc_root}")
        endif()
    endif()

    if(gsplat_ui_zenohcxx_root AND NOT DEFINED zenohcxx_DIR)
        if(EXISTS "${gsplat_ui_zenohcxx_root}/include/zenoh.hxx")
            gsplat_ui_define_zenohcxx_zenohc_target("${gsplat_ui_zenohcxx_root}")
        elseif(EXISTS "${gsplat_ui_zenohcxx_root}/lib/cmake/zenohcxx")
            set(zenohcxx_DIR "${gsplat_ui_zenohcxx_root}/lib/cmake/zenohcxx")
        elseif(EXISTS "${gsplat_ui_zenohcxx_root}/zenohcxxConfig.cmake")
            set(zenohcxx_DIR "${gsplat_ui_zenohcxx_root}")
        else()
            list(PREPEND CMAKE_PREFIX_PATH "${gsplat_ui_zenohcxx_root}")
        endif()
    endif()

    find_package(zenohc CONFIG QUIET)

    if(NOT TARGET zenohc::lib AND gsplat_ui_zenohc_root)
        gsplat_ui_define_zenohc_imported_target("${gsplat_ui_zenohc_root}")
    endif()

    if(NOT TARGET zenohc::lib)
        message(FATAL_ERROR "zenoh-c target 'zenohc::lib' was not found. Provide ZENOHC_ROOT or stage zenoh-c under ${GSPLAT_UI_LOCAL_ZENOHC_ROOT}.")
    endif()

    if(NOT TARGET zenohcxx::zenohc)
        find_package(zenohcxx CONFIG QUIET)
    endif()

    if(NOT TARGET zenohcxx::zenohc)
        message(FATAL_ERROR "zenoh-cpp target 'zenohcxx::zenohc' was not found. Provide ZENOHCXX_ROOT or stage zenoh-cpp under ${GSPLAT_UI_LOCAL_ZENOHCXX_ROOT}.")
    endif()
endif()

qt_standard_project_setup()

qt_add_executable(gsplat_ui
    src/main.cpp
    src/main_window.cpp
    src/main_window.h
    src/render_worker.cpp
    src/render_worker.h
    src/zenoh_smoke_test.cpp
    src/zenoh_smoke_test.h
)

target_include_directories(gsplat_ui PRIVATE "${GSPLAT_UI_SRC_DIR}")
target_link_libraries(gsplat_ui PRIVATE Qt6::Widgets)
target_compile_definitions(
    gsplat_ui PRIVATE
    GSPLAT_UI_TRANSPORT_CONFIG_PATH=\"${GSPLAT_UI_TRANSPORT_CONFIG_PATH}\"
)

if(GSPLAT_UI_ENABLE_ZENOH)
    target_link_libraries(gsplat_ui PRIVATE zenohcxx::zenohc)
    target_compile_definitions(gsplat_ui PRIVATE GSPLAT_UI_WITH_ZENOH=1)

    if(WIN32)
        target_link_libraries(gsplat_ui PRIVATE iphlpapi ntdll)
    endif()
else()
    target_compile_definitions(gsplat_ui PRIVATE GSPLAT_UI_WITH_ZENOH=0)
endif()

if(BUILD_TESTING)
    find_package(Qt6 REQUIRED COMPONENTS Test)

    qt_add_executable(gsplat_ui_tests
        tests/main_window_test.cpp
        src/main_window.cpp
        src/main_window.h
        src/render_worker.cpp
        src/render_worker.h
        src/zenoh_smoke_test.cpp
        src/zenoh_smoke_test.h
    )

    target_include_directories(gsplat_ui_tests PRIVATE "${GSPLAT_UI_SRC_DIR}")
    target_link_libraries(gsplat_ui_tests PRIVATE Qt6::Widgets Qt6::Test)
    target_compile_definitions(
        gsplat_ui_tests PRIVATE
        GSPLAT_UI_TRANSPORT_CONFIG_PATH=\"${GSPLAT_UI_TRANSPORT_CONFIG_PATH}\"
        GSPLAT_UI_WITH_ZENOH=0
    )

    add_test(NAME gsplat_ui_tests COMMAND gsplat_ui_tests -platform offscreen)
endif()

if(WIN32)
    set(_have_runtime_dlls $<BOOL:$<TARGET_RUNTIME_DLLS:gsplat_ui>>)
    set(_copy_runtime_dlls
        ${CMAKE_COMMAND} -E copy_if_different
        $<TARGET_RUNTIME_DLLS:gsplat_ui>
        $<TARGET_FILE_DIR:gsplat_ui>
    )
    add_custom_command(
        TARGET gsplat_ui POST_BUILD
        COMMAND "$<${_have_runtime_dlls}:${_copy_runtime_dlls}>"
        COMMAND_EXPAND_LISTS
    )

    if(GSPLAT_UI_QT_PLUGINS_DIR)
        add_custom_command(
            TARGET gsplat_ui POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E make_directory "$<TARGET_FILE_DIR:gsplat_ui>/platforms"
            COMMAND ${CMAKE_COMMAND} -E copy_if_different
                "${GSPLAT_UI_QT_PLUGINS_DIR}/platforms/qwindows$<$<CONFIG:Debug>:d>.dll"
                "$<TARGET_FILE_DIR:gsplat_ui>/platforms"
            COMMAND_EXPAND_LISTS
        )
    endif()
endif()
