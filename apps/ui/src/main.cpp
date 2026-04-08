#include <QApplication>

#include <iostream>
#include <string_view>

#include "main_window.h"
#include "zenoh_smoke_test.h"

int main(int argc, char* argv[])
{
    for (int index = 1; index < argc; ++index)
    {
        if (std::string_view(argv[index]) == "--zenoh-smoketest-only")
        {
            const ZenohSmokeResult result = runZenohSmokeTest();
            std::cout << result.summary.toStdString() << '\n';
            std::cout << result.detail.toStdString() << '\n';
            return result.success ? 0 : 1;
        }
    }

    QApplication app(argc, argv);
    app.setApplicationName("gsplat-ui");
    app.setOrganizationName("gsplat-simulator");

    MainWindow window;
    window.show();

    return app.exec();
}
