#include "zenoh_smoke_test.h"

#include <exception>

#if GSPLAT_UI_WITH_ZENOH
#include "zenoh.hxx"
#endif

ZenohSmokeResult runZenohSmokeTest()
{
#if GSPLAT_UI_WITH_ZENOH
    try
    {
#ifdef ZENOHCXX_ZENOHC
        zenoh::init_log_from_env_or("error");
#endif

        auto config = zenoh::Config::create_default();
        auto session = zenoh::Session::open(std::move(config));

        constexpr auto kKeyExpr = "demo/gsplat/ui/startup";
        constexpr auto kPayload = "gsplat_ui startup smoke test";
        session.put(kKeyExpr, kPayload);

        return {
            true,
            QStringLiteral("zenoh session open and publish succeeded."),
            QStringLiteral("Published \"%1\" to key \"%2\".")
                .arg(QString::fromUtf8(kPayload), QString::fromUtf8(kKeyExpr)),
        };
    }
    catch (const std::exception& exception)
    {
        return {
            false,
            QStringLiteral("zenoh smoke test failed."),
            QStringLiteral("Exception: %1").arg(QString::fromUtf8(exception.what())),
        };
    }
    catch (...)
    {
        return {
            false,
            QStringLiteral("zenoh smoke test failed."),
            QStringLiteral("An unknown exception was raised while opening the session or publishing."),
        };
    }
#else
    return {
        false,
        QStringLiteral("zenoh smoke test is disabled."),
        QStringLiteral("Configure CMake with GSPLAT_UI_ENABLE_ZENOH=ON to enable the smoke test."),
    };
#endif
}
