#pragma once

#include <QString>

struct ZenohSmokeResult
{
    bool success;
    QString summary;
    QString detail;
};

ZenohSmokeResult runZenohSmokeTest();
